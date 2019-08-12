import logging
from queue import Queue
from threading import Event
from functools import partial

from telegram import ParseMode
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
    update_handler,
    download_file,
    command,
    CommandType as C,
    Permission as P
)


class Bot:
    LOG_FORMAT = '[%(asctime).19s] [%(name)s] [%(levelname)s] %(message)s'
    MSG_LOG_FORMAT = ('[%(asctime).19s]'
                      ' [%(chat_id)s | %(chat_name)s]'
                      ' [%(user_id)s | %(user_link)s | %(user_name)s]'
                      ' %(message)s')

    def __init__(self, tokens, proxy=None, log_messages=False, root=None):
        if not tokens:
            raise ValueError('no tokens')

        self.logger = logging.getLogger('bot.info')
        self.msg_logger = logging.getLogger('bot.message')
        self.logger.info(
            'init: tokens=%s proxy=%s log_messages=%s root=%s',
            tokens, proxy, log_messages, root
        )

        self.tokens = [token.strip() for token in tokens]
        self.proxy = proxy.strip() if proxy is not None else None
        self.log_messages = log_messages
        self.queue = Queue()
        self.stopped = Event()

        self.updaters = [
            Updater(token, request_kwargs={
                'proxy_url': self.proxy
            })
            for token in tokens
        ]
        self.primary = self.updaters[0]

        me = self.primary.bot.get_me()
        self.logger.info('get_me: %s', me)

        self.state = BotState(self, me.id, me.username, root, proxy=self.proxy)
        self.commands = BotCommands(self)

        dispatcher = self.primary.dispatcher

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
            Filters.contact,
            self.on_contact
        ))
        dispatcher.add_handler(MessageHandler(
            Filters.audio
            | Filters.document
            | Filters.video
            | Filters.video_note,
            self.on_file
        ))

        dispatcher.add_handler(InlineQueryHandler(self.on_inline))

        for updater in self.updaters:
            dispatcher = updater.dispatcher
            dispatcher.add_error_handler(self.on_error)

    def save(self):
        self.state.save()

    def start_polling(self, interval=0.0):
        self.logger.info('start_polling %f', interval)
        for updater in self.updaters:
            updater.start_polling(interval)
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
            for i, updater in enumerate(self.updaters):
                self.logger.info('stopping updater %d', i)
                updater.stop()

    def log_update(self, update):
        self.logger.debug('log_update %s', update)

        learn = Promise.wrap(
            self.state.db.learn_update,
            update,
            ptype=PT.MANUAL
        )
        self.queue.put(learn)
        learn.catch(
            lambda ex: self.logger.error('log_update: %r: %s', ex, update)
        ).wait()

        if not self.log_messages:
            return

        if update.effective_message is not None:
            msg = update.effective_message
            extra = {
                'chat_id': msg.chat.id,
                'user_id': msg.from_user.id,
                'chat_name': sanitize_log(get_chat_title(msg.chat)),
                'user_link': '@' + sanitize_log(str(msg.from_user.username)),
                'user_name': sanitize_log('%s %s' % (
                    str(msg.from_user.first_name),
                    str(msg.from_user.last_name)
                ))
            }
            text = sanitize_log(msg.text or msg.caption or '', True)
        elif update.inline_query is not None:
            msg = update.inline_query
            extra = {
                'chat_id': None,
                'user_id': msg.from_user.id,
                'chat_name': '<inline query>',
                'user_link': '@' + sanitize_log(str(msg.from_user.username)),
                'user_name': sanitize_log('%s %s' % (
                    str(msg.from_user.first_name),
                    str(msg.from_user.last_name)
                ))
            }
            text = sanitize_log(msg.query, True)
        else:
            text = None

        if text is not None:
            self.msg_logger.info(text, extra=extra)

    def download_file(self, message, dirs, deferred=None, overwrite=False):
        self.primary.dispatcher.run_async(download_file, message,
                                          dirs, deferred, overwrite)

    def on_error(self, _, update, error):
        self.logger.error('update "%s" caused error "%s"', update, error)

    @update_handler
    def on_inline(self, bot, update):
        self.commands.inline_query(bot, update)

    @update_handler
    @command(C.REPLY_TEXT, P.IGNORED)
    def on_text(self, _, update):
        if update.message is None:
            return None
        return self.state.on_text

    @update_handler
    @command(C.REPLY_STICKER, P.IGNORED)
    def on_sticker(self, bot, update):
        if update.message is None or update.message.sticker is None:
            return None
        sticker = update.message.sticker
        if sticker.set_name is not None:
            need_sticker_set = Promise.wrap(
                self.state.db.need_sticker_set,
                sticker.set_name,
                ptype=PT.MANUAL
            )
            get_sticker_set = need_sticker_set.then(
                lambda _: bot.getStickerSet(sticker.set_name)
            )
            learn_sticker_set = get_sticker_set.then(
                self.state.db.learn_sticker_set,
                ptype=PT.MANUAL
            )
            self.queue.put(need_sticker_set)
            self.queue.put(learn_sticker_set)
            learn_sticker_set.wait()
        return self.state.on_sticker

    @update_handler
    @command(C.REPLY_TEXT, P.IGNORED)
    def on_photo(self, _, update):
        deferred = Promise.defer()
        self.download_file(update.message, self.state.file_dir, deferred)
        return partial(self.state.on_photo, deferred)

    @update_handler
    def on_contact(self, _, update):
        msg = update.message
        if msg.chat.type == msg.chat.PRIVATE:
            if msg.contact.user_id is None:
                msg.reply_text('missing user id', quote=True)
            else:
                msg.reply_text(
                    '[contact %s %s %s %s](tg://user?id=%s)' % (
                        msg.contact.phone_number,
                        msg.contact.first_name,
                        msg.contact.last_name,
                        msg.contact.user_id,
                        msg.contact.user_id
                    ),
                    parse_mode=ParseMode.MARKDOWN
                )

    @update_handler
    @command(C.REPLY_TEXT, P.IGNORED)
    def on_voice(self, _, update):
        self.download_file(update.message, self.state.file_dir)
        return self.state.on_voice

    @update_handler
    def on_file(self, _, update):
        self.download_file(update.message, self.state.file_dir)
