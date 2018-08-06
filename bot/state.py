import os
import re
import random
import sqlite3
import logging
import tempfile
import subprocess
from collections import defaultdict
from threading import Lock

from telegram import ChatAction, TelegramError
from telegram.ext import Dispatcher

from .util import (
    strip_command,
    get_message_text,
    get_message_filename,
    reply_text,
    reply_photo,
    FILE_TYPES
)
from .context_cache import ContextCache
from .error import CommandError


class BotState:
    INIT_DATABASE = [
        'PRAGMA foreign_keys=1',
        'CREATE TABLE IF NOT EXISTS `user` ('
        '  `id` INTEGER NOT NULL PRIMARY KEY,'
        '  `name` TEXT,'
        '  `permission` INTEGER NOT NULL DEFAULT 0'
        ')',
        'CREATE TABLE IF NOT EXISTS `chat` ('
        '  `id` INTEGER NOT NULL PRIMARY KEY,'
        '  `title` TEXT,'
        '  `type` TEXT NOT NULL DEFAULT "private",'
        '  `context` TEXT,'
        '  `order` INTEGER,'
        '  `learn` BOOLEAN NOT NULL DEFAULT 0,'
        '  `trigger` TEXT,'
        '  `reply_to_bots` INTEGER DEFAULT 80'
        ')',
        'CREATE TABLE IF NOT EXISTS `chat_user` ('
        '  `chat_id` REFERENCES `chat`(`id`),'
        '  `user_id` REFERENCES `user`(`id`)'
        ')',
        'CREATE TABLE IF NOT EXISTS `sticker_set` ('
        '  `id` INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,'
        '  `name` TEXT NOT NULL,'
        '  `title` TEXT NOT NULL'
        ')',
        'CREATE TABLE IF NOT EXISTS `sticker` ('
        '  `id` INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,'
        '  `set` REFERENCES `sticker_set`(`id`),'
        '  `file_id` TEXT NOT NULL,'
        '  `emoji` TEXT'
        ')',
        'CREATE INDEX IF NOT EXISTS `chat_user_id` ON `chat_user` (`user_id`)',
        'CREATE INDEX IF NOT EXISTS `chat_id` ON `chat_user` (`chat_id`)',
        'CREATE INDEX IF NOT EXISTS `sticker_emoji` ON `sticker` (`emoji`)',
        'CREATE INDEX IF NOT EXISTS `sticker_set_name` ON `sticker_set` (`name`)'
    ]

    ASYNC_MAX_DEFAULT = 4
    PROCESS_TIMEOUT_DEFAULT = 30

    def __init__(self,
                 id_,
                 username,
                 root=None,
                 async_max=ASYNC_MAX_DEFAULT,
                 process_timeout=PROCESS_TIMEOUT_DEFAULT):
        if root is None:
            root = os.path.expanduser('~/.bot')

        self.id = id_
        self.username = username
        self.root = root
        self.logger = logging.getLogger('bot.state')
        self.context = ContextCache(os.path.join(self.root, 'data'))

        self.default_file_dir = os.path.join(self.root, 'document')
        self.file_dir = defaultdict(lambda: self.default_file_dir)
        self.tmp_dir = tempfile.mkdtemp(prefix=__name__)

        self.async_lock = Lock()
        self.async_running = 0
        self.async_max = async_max
        self.process_timeout = process_timeout

        os.makedirs(self.default_file_dir, exist_ok=True)
        for type_ in FILE_TYPES:
            dir_ = os.path.join(self.root, type_)
            os.makedirs(dir_, exist_ok=True)
            self.file_dir[type_] = dir_

        self.db = sqlite3.connect(os.path.join(self.root, 'bot.db'))
        self.cursor = self.db.cursor()
        for cmd in self.INIT_DATABASE:
            self.cursor.execute(cmd)
        self.db.commit()

    def save(self):
        self.logger.info('saving bot state')
        self.db.commit()

    def run_async(self, func, *args, **kwargs):
        def _run_async():
            try:
                func(*args, **kwargs)
            finally:
                with self.async_lock:
                    self.async_running -= 1
                self.logger.info(
                    'run_async end %s %d',
                    func.__name__, self.async_running
                )

        with self.async_lock:
            if self.async_running >= self.async_max:
                msg = 'run_async: %s: queue full' % func.__name__
                self.logger.warning(msg)
                raise CommandError(msg)
            self.async_running += 1

        try:
            self.logger.info(
                'run_async start %s %d',
                func.__name__, self.async_running
            )
            Dispatcher.get_instance().run_async(_run_async)
        except Exception as ex:
            self.logger.error('run_async error %r', ex)
            with self.async_lock:
                self.async_running -= 1
            raise

    def get_chat(self, chat, fields='*'):
        query = 'SELECT %s FROM `chat` WHERE id=?' % fields
        while True:
            self.cursor.execute(query, (chat.id,))
            row = self.cursor.fetchone()
            if row is not None:
                return row
            self.cursor.execute(
                'INSERT INTO `chat`'
                ' (`id`, `title`, `type`)'
                ' VALUES (?, ?, ?)',
                (chat.id, chat.title, chat.type)
            )
            self.db.commit()

    def get_chat_context(self, chat):
        context = self.get_chat(chat, 'context')[0]
        if context is None:
            raise CommandError('generator context is not set')
        return self.context.get(context)

    def get_chat_settings(self, chat):
        try:
            return self.get_chat_context(chat).settings
        except CommandError:
            return self.context.defaults

    def list_contexts(self, update):
        ret = self.context.list(update.message.chat.id)
        if ret:
            return 'select context', ret
        raise CommandError('no context available')

    def set_context(self, update):
        query = update.callback_query
        chat = query.message.chat
        name = query.data

        self.logger.info('set_context %s %s', chat.id, name)
        prev_context, prev_order, prev_learn = self.get_chat(
            chat,
            '`context`,`order`,`learn`'
        )

        if name == 'new private context':
            self.logger.info('creating private context %s', chat.id)
            context = self.context.get_private(chat)
            name = context.name
            learn = True
        else:
            context = self.context.get(name)
            learn = prev_learn

        if not context.is_writable:
            learn = False

        orders = context.get_orders()
        if prev_order not in orders:
            order = next(iter(orders))
        else:
            order = prev_order

        self.cursor.execute(
            'UPDATE chat'
            ' SET `context`=?, `order`=?, `learn`=?'
            ' WHERE `id`=?',
            (name, order, learn, chat.id)
        )
        self.db.commit()
        return 'context: %s -> %s\norder: %s -> %s\nlearn: %s -> %s' % (
            prev_context, name,
            prev_order, order,
            bool(prev_learn), bool(learn)
        )

    def list_orders(self, update):
        context = self.get_chat_context(update.message.chat)
        return 'select order', context.get_orders()

    def set_order(self, update):
        query = update.callback_query
        chat = query.message.chat
        order = int(query.data)
        self.logger.info('set_order %s %s', chat.id, order)
        prev = self.get_chat(chat, '`order`')[0]
        context = self.get_chat_context(chat)
        if order not in context.get_orders():
            raise CommandError('invalid order: %s: not in %s' % (
                order, context.get_orders()
            ))
        self.cursor.execute(
            'UPDATE `chat` SET `order`=? WHERE `id`=?',
            (order, chat.id)
        )
        self.db.commit()
        return 'order: %s -> %s' % (prev, order)

    def list_learn_modes(self, update):
        context = self.get_chat_context(update.message.chat)
        if not context.is_writable:
            raise CommandError('context "%s" is read only' % context.name)
        return 'select learn mode', ['on', 'off']

    def set_learn_mode(self, update):
        query = update.callback_query
        chat = query.message.chat
        learn = query.data.lower() == 'on'
        self.logger.info('set_learn %s %s', chat.id, learn)
        prev = bool(self.get_chat(chat, '`learn`')[0])
        context = self.get_chat_context(chat)
        if learn and not context.is_writable:
            raise CommandError('context %s is read only' % context)
        self.cursor.execute(
            'UPDATE `chat` SET `learn`=? WHERE `id`=?',
            (learn, chat.id)
        )
        self.db.commit()
        return 'learn: %s -> %s' % (prev, learn)

    def confirm_delete_private_context(self, update):
        chat = update.message.chat
        if chat.type != chat.PRIVATE:
            raise CommandError(
                'permission denied: chat.type ("%s") != "%s"'
                % (chat.type, chat.PRIVATE)
            )
        if not self.context.has_private(chat):
            raise CommandError('context "%s" does not exist' % chat.id)
        return 'delete private context "%s"?' % chat.id, ['yes', 'no']

    def delete_private_context(self, update):
        query = update.callback_query
        chat = query.message.chat
        if query.data.lower() == 'yes':
            self.context.delete_private(chat)
            self.cursor.execute(
                'UPDATE chat SET context=NULL WHERE id=? AND context=?',
                (chat.id, str(chat.id))
            )
            self.db.commit()
            return 'deleted private context "%s"' % chat.id
        return 'cancelled'

    def show_settings(self, update):
        context, order, learn, trigger, reply_to_bots = self.get_chat(
            update.message.chat,
            '`context`,`order`,`learn`,`trigger`,`reply_to_bots`'
        )
        learn = bool(learn)
        reply = (
            'settings:\n'
            '    context: %s\n'
            '    markov chain order: %s\n'
            '    learn: %s\n'
            '    trigger: %s\n'
            #'    probability of replying to bots: %s%%\n'
        ) % (context, order, learn, trigger)
        return reply

    def set_bot_reply_probability(self, update):
        message = update.message
        value = strip_command(message.text)
        if not value:
            raise CommandError('usage: /setbotreply <0-100>')
        try:
            value = min(100, max(int(value), 0))
        except ValueError as ex:
            raise CommandError(ex)
        prev = self.get_chat(message.chat, 'reply_to_bots')[0]
        self.cursor.execute(
            'UPDATE chat SET reply_to_bots=? WHERE id=?',
            (value, message.chat.id)
        )
        self.db.commit()
        return 'probability of replying to bots: %d%% -> %d%%' % (prev, value)

    def set_trigger(self, update):
        message = update.message
        expr = strip_command(message.text)
        if not expr:
            raise CommandError('usage: /settrigger <regexp>')
        else:
            try:
                re.compile(expr)
            except re.error as ex:
                raise CommandError(ex)
        prev = self.get_chat(message.chat, 'trigger')[0]
        self.cursor.execute(
            'UPDATE chat SET trigger=? WHERE id=?',
            (expr, message.chat.id)
        )
        self.db.commit()
        return 'trigger: %s -> %s' % (prev, expr)

    def remove_trigger(self, update):
        prev = self.get_chat(update.message.chat, 'trigger')[0]
        self.cursor.execute(
            'UPDATE chat SET trigger=NULL WHERE id=?',
            (update.message.chat.id,)
        )
        self.db.commit()
        return 'trigger: %s -> None' % prev

    def _need_reply(self, message):
        reply = False
        quote = False
        text = get_message_text(message)

        trigger = self.get_chat(message.chat, 'trigger')

        if message.chat.type == message.chat.PRIVATE:
            self.logger.info('private chat: reply=True')
            reply = True
        elif (message.reply_to_message
              and message.reply_to_message.from_user.id == self.id):
            self.logger.info('reply to self: reply=True')
            quote = True
            reply = True
        elif text:
            if self.username in text:
                self.logger.info('username in message text: reply=True')
                quote = True
                reply = True
            elif re.search(trigger, text, re.I):
                self.logger.info('trigger: reply=True')
                quote = True
                reply = True

        #if reply:
        #    if message.from_user.is_bot:
        #        rnd = randint(0, 99)
        #        self.logger.info('reply to bot: %d / %d', rnd, reply_to_bots)
        #        if rnd >= reply_to_bots:
        #            self.logger.info('not replying to bot')
        #            reply = False

        return reply, quote

    def need_sticker_set(self, name):
        self.cursor.execute(
            'SELECT COUNT(*) FROM `sticker_set` WHERE `name`=?',
            (name,)
        )
        res = self.cursor.fetchone()[0]
        self.logger.info('need_sticker_set: name=%s count=%s', name, res)
        if res:
            raise CommandError('sticker set exists')
        return True

    def learn_sticker_set(self, set_):
        self.logger.info(
            'learn_sticker_set: name=%s title=%s',
            set_.name, set_.title
        )
        self.cursor.execute(
            'INSERT INTO `sticker_set` (`name`, `title`) VALUES (?, ?)',
            (set_.name, set_.title)
        )
        self.cursor.execute(
            'SELECT `id` FROM `sticker_set` WHERE `name`=?',
            (set_.name,)
        )
        set_id = self.cursor.fetchone()[0]
        for sticker in set_.stickers:
            self.cursor.execute(
                'INSERT INTO'
                ' `sticker` (`set`, `file_id`, `emoji`)'
                ' VALUES (?, ?, ?)',
                (set_id, sticker.file_id, sticker.emoji)
            )
        self.db.commit()

    def random_text(self, update):
        context, order = self.get_chat(update.message.chat, '`context`,`order`')
        if context is None:
            self.logger.info('no context')
            raise CommandError('generator context is not set')
        context = self.context.get(context)
        try:
            return context.random_text(order), True
        except KeyError as ex:
            self.logger.error(ex)
            return None

    def random_sticker(self):
        self.cursor.execute(
            'SELECT `file_id` FROM `sticker` ORDER BY RANDOM() LIMIT 1'
        )
        res = self.cursor.fetchone()
        if res is None:
            return None
        return res[0]

    def filter_image(self, update, download, settings, quote=False):
        output = os.path.join(
            self.tmp_dir,
            get_message_filename(update.message) + '_filtered.jpg'
        )
        self.logger.info('filter %s', output)

        try:
            update.message.bot.send_chat_action(
                update.message.chat_id,
                ChatAction.UPLOAD_PHOTO
            )
        except TelegramError as ex:
            self.logger.error('send_chat_action: %r', ex)

        download.then(
            lambda fname: subprocess.check_output(
                (os.path.join(self.root, 'scripts', 'filter'),
                 '384x384', settings['filter'], fname, output
                ),
                stderr=subprocess.STDOUT,
                timeout=self.process_timeout
            )
        ).then(
            lambda _: reply_photo(update, output, quote)
        ).catch(
            lambda err: reply_text(update, err, quote)
        ).wait()

    def on_text(self, update):
        message = update.message
        reply, quote = self._need_reply(message)

        context, order, learn = self.get_chat(
            message.chat,
            '`context`,`order`,`learn`'
        )

        context = self.context.get(context)
        text = message.text
        res = None

        private = self.context.get_private(message.chat)
        if private is not context:
            self.logger.info('learn private')
            private.learn_text(text)

        if context is not None:
            if reply:
                try:
                    reply = context.reply_text(text, order)
                    self.logger.info('reply: "%s"', reply)
                    if reply:
                        res = (reply, quote)
                except KeyError as ex:
                    self.logger.error(ex)
            if learn:
                if message.from_user.is_bot:
                    self.logger.info('not learning from bots')
                else:
                    self.logger.info('learn')
                    context.learn_text(text)
        elif reply:
            self.logger.info('no context')
            raise CommandError('generator context is not set')

        return res

    def on_sticker(self, update):
        message = update.message
        reply, quote = self._need_reply(message)
        if reply:
            res = self.random_sticker()
            self.logger.info(res)
            if res is None:
                return None
            return res, quote
        return None

    def on_photo(self, deferred, update):
        message = update.message
        reply, quote = self._need_reply(message)
        settings = self.get_chat_settings(update.message.chat)
        if not reply:
            return None
        self.run_async(
            self.filter_image,
            update, deferred.promise, settings, quote
        )
        return None

    def on_status_update(self, type_, update):
        self.logger.info('status update: %s', type_)
        if type_ is None:
            return None
        try:
            settings = self.get_chat_settings(update.message.chat)
            return random.choice(settings['on_' + type_]), True
        except KeyError as ex:
            self.logger.warning('status_update: %s: %r', type_, ex)
            return None
