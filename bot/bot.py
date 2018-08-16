import os
import logging
from queue import Queue
from threading import Event
from functools import partial

from telegram.ext import (
    Updater,
    MessageHandler,
    InlineQueryHandler,
    run_async
)
from telegram.ext.filters import Filters

from .state import BotState
from .commands import BotCommands
from .promise import Promise, PromiseType as PT
from .util import (
    sanitize_log,
    get_chat_title,
    get_message_filename,
    update_handler,
    get_file,
    command,
    CommandType as C
)


class Bot:
    LOG_FORMAT = '[%(asctime).19s] [%(name)s] [%(levelname)s] %(message)s'
    MSG_LOG_FORMAT = ('[%(asctime).19s]'
                      ' [%(chat_id)s | %(chat_name)s]'
                      ' [%(user_id)s | %(user_link)s | %(user_name)s]'
                      ' %(message)s')

    def __init__(self, token, proxy=None, log_messages=False, root=None):
        self.logger = logging.getLogger('bot.info')
        self.msg_logger = logging.getLogger('bot.message')
        self.logger.info(
            'init: token=%s proxy=%s log_messages=%s root=%s',
            token, proxy, log_messages, root
        )

        self.token = token.strip()
        self.proxy = proxy.strip()
        self.log_messages = log_messages
        self.queue = Queue()
        self.stopped = Event()

        self.updater = Updater(self.token, request_kwargs={
            'proxy_url': self.proxy
        })

        me = self.updater.bot.get_me()
        self.logger.info('get_me: %s', me)

        self.state = BotState(me.id, me.username, root)
        self.commands = BotCommands(self)

        dispatcher = self.updater.dispatcher

        dispatcher.add_handler(MessageHandler(
            Filters.text,
            self.on_text,
            edited_updates=True
        ))
        dispatcher.add_handler(MessageHandler(
            Filters.sticker,
            self.on_sticker
        ))
        dispatcher.add_handler(MessageHandler(
            Filters.photo,
            self.on_photo
        ))
        dispatcher.add_handler(MessageHandler(
            Filters.voice,
            self.on_voice
        ))
        dispatcher.add_handler(MessageHandler(
            Filters.photo,
            self.on_photo
        ))
        dispatcher.add_handler(MessageHandler(
            Filters.audio
            | Filters.document
            | Filters.video
            | Filters.video_note,
            self.on_file
        ))

        dispatcher.add_handler(InlineQueryHandler(self.on_inline))
        dispatcher.add_error_handler(self.on_error)

    def save(self):
        self.state.save()

    def start_polling(self, interval=0.0):
        self.logger.info('start_polling %f', interval)
        self.updater.start_polling(interval)
        self.main_loop()

    def main_loop(self):
        self.logger.info('main loop')
        promise = None
        while True:
            try:
                promise = self.queue.get()
                if not isinstance(promise, Promise):
                    self.logger.error(
                        'main loop: invalid queue item: %s',
                        promise
                    )
                    continue
                promise.run()
            except (KeyboardInterrupt, SystemExit) as ex:
                self.logger.info(ex)
                self.logger.info('stopping main loop')
                try:
                    if promise is not None:
                        promise.run()
                        self.queue.task_done()
                        promise = None
                finally:
                    self.stop()
                return
            except Exception as ex:
                self.logger.error(ex)
            finally:
                if promise is not None:
                    self.queue.task_done()
                    promise = None

    def stop(self):
        try:
            self.logger.info('stopping bot')
            self.stopped.set()
            promise = None
            while not self.queue.empty():
                try:
                    promise = self.queue.get()
                    if not isinstance(promise, Promise):
                        self.logger.error(
                            'stop: invalid queue item: %s',
                            promise
                        )
                        continue
                    promise.run()
                except Exception as ex:
                    self.logger.error(ex)
                finally:
                    if promise is not None:
                        self.queue.task_done()
                        promise = None
        finally:
            self.save()
            self.logger.info('stopping updater')
            self.updater.stop()

    def log_message(self, msg):
        self.logger.debug('message %s', msg)
        if not self.log_messages:
            return
        extra = {
            'chat_id': msg.chat.id,
            'user_id': msg.from_user.id,
            'chat_name': sanitize_log(get_chat_title(msg.chat)),
            'user_link': '@' + sanitize_log(str(msg.from_user.username)),
            'user_name': sanitize_log('%s %s' % (str(msg.from_user.first_name),
                                                 str(msg.from_user.last_name)))
        }
        text = sanitize_log(msg.text, True)
        self.msg_logger.info(text, extra=extra)

    def on_error(self, _, update, error):
        self.logger.error('update "%s" caused error "%s"', update, error)

    @run_async
    def download(self, message, deferred=None):
        try:
            ftype, fid = get_file(message)
            fdir = self.state.file_dir[ftype]
            fname = os.path.join(fdir, get_message_filename(message))
            self.logger.info('download %s -> %s', ftype, fname)
            self.updater.bot.get_file(fid).download(fname)
            self.logger.info('download complete: %s -> %s', ftype, fname)
        except BaseException as ex:
            if deferred is not None:
                deferred.reject(ex)
            raise
        else:
            if deferred is not None:
                deferred.resolve(fname)

    @update_handler
    def on_inline(self, _, update):
        pass

    @update_handler
    @command(C.REPLY_TEXT)
    def on_text(self, _, update):
        self.log_message(update.effective_message)
        if update.message is None:
            return None
        return self.state.on_text

    @update_handler
    @command(C.REPLY_STICKER)
    def on_sticker(self, bot, update):
        if update.message is None or update.message.sticker is None:
            return None
        sticker = update.message.sticker
        if sticker.set_name is not None:
            need_sticker_set = Promise.wrap(
                self.state.need_sticker_set,
                sticker.set_name,
                ptype=PT.MANUAL
            )
            get_sticker_set = need_sticker_set.then(
                lambda _: bot.getStickerSet(sticker.set_name)
            )
            learn_sticker_set = get_sticker_set.then(
                self.state.learn_sticker_set,
                ptype=PT.MANUAL
            )
            self.queue.put(need_sticker_set)
            self.queue.put(learn_sticker_set)
            learn_sticker_set.wait()
        return self.state.on_sticker

    @update_handler
    @command(C.REPLY_TEXT)
    def on_photo(self, _, update):
        deferred = Promise.defer()
        self.download(update.message, deferred)
        return partial(self.state.on_photo, deferred)

    @update_handler
    @command(C.REPLY_TEXT)
    def on_voice(self, _, update):
        self.download(update.message)
        return self.state.on_voice

    @update_handler
    def on_file(self, _, update):
        self.download(update.message)
