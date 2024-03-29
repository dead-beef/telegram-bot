import logging
from queue import Queue
from threading import Event
from functools import partial

from pony.orm import db_session

from telegram import ParseMode
from telegram.ext import (
    Updater,
    MessageHandler,
    InlineQueryHandler
)
from telegram.ext.filters import Filters

from .error import CommandError
from .state import BotState
from .commands import BotCommands
from .promise import Promise, PromiseType as PT
from .util import (
    update_handler,
    download_file,
    command,
    CommandType as C,
    Permission as P
)


class Bot:
    LOG_FORMAT = '[%(asctime).19s] [%(name)s] [%(levelname)s] %(message)s'

    def __init__(self, tokens, proxy=None, root=None):
        if not tokens:
            raise ValueError('no tokens')

        self.logger = logging.getLogger('bot.info')
        self.logger.info(
            'init: tokens=%s proxy=%s root=%s',
            tokens, proxy, root
        )

        self.tokens = [token.strip() for token in tokens]
        self.proxy = proxy.strip() if proxy is not None else None
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
            Filters.text | Filters.command,
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

        #for updater in self.updaters:
        #    dispatcher = updater.dispatcher
        #    dispatcher.add_error_handler(self.on_error)

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
            self.state.learn_update,
            update,
            ptype=PT.MANUAL
        )
        self.queue.put(learn)
        learn.catch(
            lambda ex: self.logger.error('log_update: %r: %s', ex, update)
        ).wait()

    def download_file(self, message, dirs, deferred=None, overwrite=False):
        self.primary.dispatcher.run_async(download_file, message,
                                          dirs, deferred, overwrite)

    def on_error(self, *args):
        self.logger.error(
            'update "%r" caused error "%r"',
            args[-2],
            args[-1]
        )

    @update_handler
    def on_inline(self, bot, update):
        self.commands.inline_query(bot, update)

    @db_session
    def _on_text(self, bot, update):
        self.state.apply_aliases(update)
        if update.message.text[0] == '/':
            return self.commands.on_command(bot, update)
        return self.state.on_text(update)

    @update_handler
    @command(C.REPLY_TEXT, P.IGNORED)
    def on_text(self, bot, update):
        if update.message is None:
            return None
        return partial(self._on_text, bot)

    @update_handler
    @command(C.REPLY_STICKER, P.IGNORED)
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
                lambda res: bot.getStickerSet(sticker.set_name) if res else None
            )
            learn_sticker_set = get_sticker_set.then(
                self.state.learn_sticker_set,
                ptype=PT.MANUAL
            )
            self.queue.put(need_sticker_set)
            self.queue.put(learn_sticker_set)
            learn_sticker_set.wait()
            if isinstance(learn_sticker_set.value, Exception):
                self.logger.warning(
                    'learn_sticker_set: error: %r',
                    learn_sticker_set.value
                )
        return self.state.on_sticker

    @update_handler
    @command(C.REPLY_TEXT, P.IGNORED)
    def on_photo(self, _, update):
        return self.state.on_photo

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
        return self.state.on_voice

    @update_handler
    def on_file(self, _, update):
        return self.state.on_file
