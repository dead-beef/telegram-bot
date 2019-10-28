import os
import re
import json
import html
import random
import logging
import tempfile
import subprocess
from collections import defaultdict
from threading import Lock

from telegram import ChatAction, TelegramError, ParseMode
from telegram.ext import Dispatcher

from .util import (
    trunc,
    strip_command,
    get_message_text,
    get_message_filename,
    reply_text,
    reply_photo,
    FILE_TYPES
)
from .database import BotDatabase
from .context_cache import ContextCache
from .formatter import Formatter
from .error import CommandError
from .search import Search


class BotState:
    ASYNC_MAX_DEFAULT = 4
    PROCESS_TIMEOUT_DEFAULT = 60
    QUERY_TIMEOUT_DEFAULT = 5
    RE_COMMAND = re.compile(r'^/([^@\s]+)')
    RE_COMMAND_NO_ARGS = re.compile(r'^/([^@\s]+)(@\S+)?\s*$')

    def __init__(self,
                 bot, id_, username,
                 root=None,
                 async_max=ASYNC_MAX_DEFAULT,
                 process_timeout=PROCESS_TIMEOUT_DEFAULT,
                 query_timeout=QUERY_TIMEOUT_DEFAULT,
                 proxy=None):
        if root is None:
            root = os.path.expanduser('~/.bot')

        self.bot = bot
        self.id = id_
        self.username = username
        self.root = root
        self.logger = logging.getLogger('bot.state')
        self.context = ContextCache(os.path.join(self.root, 'data'))

        self.default_file_dir = os.path.join(self.root, 'document')
        self.file_dir = defaultdict(lambda: self.default_file_dir)
        self.tmp_dir = tempfile.mkdtemp(prefix=__name__ + '.')

        self.search = Search(proxy=proxy)

        formatter = os.path.join(
            self.context.root_settings,
            'formatter.json'
        )
        if os.path.isfile(formatter):
            with open(formatter) as fp:
                formatter = json.load(fp)
            self.formatter = Formatter.load(formatter)
        else:
            self.logger.warning('formatter settings not found: %s', formatter)
            self.formatter = Formatter()

        self.async_lock = Lock()
        self.async_running = 0
        self.async_max = async_max
        self.process_timeout = process_timeout
        self.query_timeout = query_timeout

        os.makedirs(self.default_file_dir, exist_ok=True)
        for type_ in FILE_TYPES:
            dir_ = os.path.join(self.root, type_)
            os.makedirs(dir_, exist_ok=True)
            self.file_dir[type_] = dir_

        self.db = BotDatabase(os.path.join(self.root, 'bot.db'))

    def save(self):
        self.logger.info('saving bot state')
        self.db.save()

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
            self.bot.primary.dispatcher.run_async(_run_async)
        except Exception as ex:
            self.logger.error('run_async error %r', ex)
            with self.async_lock:
                self.async_running -= 1
            raise

    def apply_aliases(self, update):
        msg = update.message
        if not msg:
            return

        chat = msg.chat
        reply = msg.reply_to_message
        msg = get_message_text(msg)

        if reply:
            reply = strip_command(get_message_text(reply))
            if self.RE_COMMAND_NO_ARGS.match(msg):
                msg = '%s %s' % (msg, reply)

        for _, expr, repl in self.db.get_chat_aliases(chat):
            msg = re.sub(expr, repl, msg, flags=re.I)

        if reply and self.RE_COMMAND_NO_ARGS.match(msg):
            msg = '%s %s' % (msg, reply)

        update.message.text = msg

    def get_chat_context(self, chat):
        context = self.db.get_chat_data(chat, 'context')
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
        prev_context, prev_order, prev_learn = self.db.get_chat_data(
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

        self.db.set_chat_data(chat, context=name, order=order, learn=learn)

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
        context = self.get_chat_context(chat)
        if order not in context.get_orders():
            raise CommandError('invalid order: %s: not in %s' % (
                order, context.get_orders()
            ))
        prev = self.db.get_chat_data(chat, '`order`')
        self.db.set_chat_data(chat, order=order)
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
        context = self.get_chat_context(chat)
        if learn and not context.is_writable:
            raise CommandError('context %s is read only' % context)
        prev = bool(self.db.get_chat_data(chat, '`learn`'))
        self.db.set_chat_data(chat, learn=learn)
        return 'learn: %s -> %s' % (prev, learn)

    def confirm_delete_private_context(self, update):
        chat = update.message.chat
        if not self.context.has_private(chat):
            raise CommandError('context "%s" does not exist' % chat.id)
        return 'delete private context "%s"?' % chat.id, ['yes', 'no']

    def delete_private_context(self, update):
        query = update.callback_query
        chat = query.message.chat
        if query.data.lower() == 'yes':
            context = self.db.get_chat_data(chat, 'context')
            if context == str(chat.id):
                self.db.set_chat_data(chat, context=None)
            self.context.delete_private(chat)
            return 'deleted private context "%s"' % chat.id
        return 'cancelled'

    def show_settings(self, update):
        context, order, learn, trigger = self.db.get_chat_data(
            update.message.chat,
            '`context`,`order`,`learn`,`trigger`'
        )
        learn = bool(learn)
        reply = (
            'settings:\n'
            '    context: %s\n'
            '    markov chain order: %s\n'
            '    learn: %s\n'
            '    trigger: %s\n'
        ) % (context, order, learn, trigger)
        return reply

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
        prev = self.db.get_chat_data(message.chat, 'trigger')
        self.db.set_chat_data(message.chat, trigger=expr)
        return 'trigger: %s -> %s' % (prev, expr)

    def remove_trigger(self, update):
        prev = self.db.get_chat_data(update.message.chat, 'trigger')
        self.db.set_chat_data(update.message.chat, trigger=None)
        return 'trigger: %s -> None' % prev

    def set_reply_length(self, update):
        message = update.message
        length = strip_command(message.text)
        if not length:
            raise CommandError('usage: /setreplylength <number>')
        try:
            length = max(8, min(int(length), 256))
        except ValueError as ex:
            raise CommandError(ex)
        prev = self.db.get_chat_data(message.chat, 'reply_max_length')
        self.db.set_chat_data(message.chat, reply_max_length=length)
        return 'max reply length: %d -> %d' % (prev, length)

    def _need_reply(self, message):
        reply = False
        quote = False
        text = get_message_text(message)

        if message.chat.type == message.chat.PRIVATE:
            self.logger.info('private chat: reply=True')
            reply = True
        elif (message.reply_to_message
              and message.reply_to_message.from_user.id == self.id):
            self.logger.info('reply to self: reply=True')
            quote = True
            reply = True
        elif text:
            if text.strip().startswith('/image'):
                self.logger.info('image command: reply=True')
                quote = True
                reply = True
            elif self.username in text:
                self.logger.info('username in message text: reply=True')
                quote = True
                reply = True
            else:
                trigger = self.db.get_chat_data(message.chat, 'trigger')
                if trigger is not None and re.search(trigger, text, re.I):
                    self.logger.info('trigger: reply=True')
                    quote = True
                    reply = True

        return reply, quote

    def random_text(self, update):
        context, order, length = self.db.get_chat_data(
            update.message.chat,
            '`context`,`order`,`reply_max_length`'
        )
        if context is None:
            self.logger.info('no context')
            raise CommandError('generator context is not set')
        context = self.context.get(context)
        try:
            return context.random_text(order, length), True
        except KeyError as ex:
            self.logger.error(ex)
            return None

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
                 settings['filter_size'], settings['filter'], fname, output
                ),
                stderr=subprocess.STDOUT,
                timeout=self.process_timeout
            )
        ).then(
            lambda _: reply_photo(update, output, quote)
        ).catch(
            lambda err: reply_text(update, err, quote)
        ).wait()

    def list_sticker_sets(self, update):
        page_size = 25
        if update.callback_query:
            page = int(update.callback_query.data)
        else:
            page = 1
        sets, pages = self.db.get_sticker_sets(page, page_size)
        if pages <= 1:
            return 'no sticker sets', 1
        res = '\n'.join(
            '{0}. [{1}](https://t.me/addstickers/{2})'.format(*set_)
            for set_ in sets
        )
        res = 'sticker sets page %d / %d:\n%s' % (page, pages, res)
        return res, page, pages, False, ParseMode.MARKDOWN

    def list_users(self, update):
        page_size = 10
        if update.callback_query:
            page = int(update.callback_query.data)
        else:
            page = 1
        if update.effective_chat.type != update.effective_message.chat.PRIVATE:
            permission = 0
        else:
            permission = self.db.get_user_data(update.effective_user, 'permission')
        users, pages = self.db.get_users(page, page_size, permission)
        if not users:
            return 'no users', 1, 1, True
        offset = page_size * (page - 1)
        res = '\n'.join(
            '{0}. ({5}) <a href="tg://user?id={1}">{1}</a> {2} {3} {4}'
            .format(
                i,
                user[0],
                html.escape(user[1] if user[1] is not None
                            else '<no phone>'),
                html.escape(user[2] or '<no name>'),
                html.escape(user[3] or '<no username>'),
                user[4]
            )
            for i, user in enumerate(users, offset + 1)
        )
        res = 'users page %d / %d:\n\n%s' % (page, pages, res)
        return res, page, pages, False, ParseMode.HTML

    def list_search_requests(self, update):
        page_size = 10
        if update.callback_query:
            page = int(update.callback_query.data)
        else:
            page = 1
        offset = page_size * (page - 1)
        requests, pages = self.db.get_search_log(page, page_size)
        res = '\n'.join(
            '{0}. {1} (<b>{2}</b>)'
            .format(
                i,
                html.escape(query),
                html.escape(user)
            )
            for i, (query, user) in enumerate(requests, offset + 1)
        )
        res = 'pic log page %d / %d:\n\n%s' % (page, pages, res)
        return res, page, pages, False, ParseMode.HTML

    def get_search_stats(self, update):
        page_size = 10
        if update.callback_query:
            page = int(update.callback_query.data)
        else:
            page = 1
        stats, pages = self.db.get_search_stats(page, page_size)
        offset = page_size * (page - 1)
        res = '\n'.join(
            '{0}. {1} (<b>{2}</b>)'
            .format(i, html.escape(query), count)
            for i, (query, count) in enumerate(stats, offset + 1)
        )
        res = 'pic stats page %d / %d:\n\n%s' % (page, pages, res)
        return res, page, pages, False, ParseMode.HTML

    def query_db(self, query):
        self.db.cursor.execute(query)
        row_count = self.db.cursor.rowcount
        self.db.save()
        rows = self.db.cursor.fetchall()
        res = '\n'.join(' '.join(repr(col) for col in row) for row in rows)
        if not res:
            res = '%s rows affected' % row_count
        else:
            res = trunc(res)
        return res, True

    def on_text(self, update):
        message = update.message
        reply, quote = self._need_reply(message)

        context, order, learn, length = self.db.get_chat_data(
            message.chat,
            '`context`,`order`,`learn`,`reply_max_length`'
        )

        context = self.context.get(context)
        text = message.text
        res = None

        private = self.context.get_private(message.chat)

        self.logger.info('learn private')
        private.learn_text(text)

        if context is not None:
            if reply:
                try:
                    reply = context.reply_text(text, order, length)
                    self.logger.info('reply: "%s"', reply)
                    if reply:
                        res = (reply, quote)
                except KeyError as ex:
                    self.logger.error(ex)
            if learn:
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
            res = self.db.random_sticker()
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

    def on_voice(self, update):
        message = update.message
        reply, quote = self._need_reply(message)
        if not reply:
            return None
        return 'on_voice', quote

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
