import os
import re
import json
import time
import random
import logging
import tempfile
import subprocess
from collections import defaultdict
from threading import Lock

from pony.orm import db_session
from telegram import ChatAction, TelegramError

from .util import (
    strip_command,
    get_file,
    get_message_text,
    get_message_filename,
    reply_text,
    reply_photo,
    Permission as P,
    FILE_TYPES
)
from .models import (
    connect, flush, get_or_create, update_or_create,
    StickerSet, Sticker, User, UserPhone, Chat, Message,
    SearchQuery, SearchLog
)
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
                 proxy=None,
                 user_update_interval=86400,
                 chat_update_interval=86400,
                 sticker_set_update_interval=86400):
        if root is None:
            root = os.path.expanduser('~/.bot')

        self.bot = bot
        self.id = id_
        self.username = username
        self.root = root
        self.user_update_interval = user_update_interval
        self.chat_update_interval = chat_update_interval
        self.sticker_set_update_interval = sticker_set_update_interval
        self.logger = logging.getLogger('bot.state')
        self.context = ContextCache(os.path.join(self.root, 'data'))

        self.default_file_dir = os.path.join(self.root, 'document')
        self.file_dir = defaultdict(lambda: self.default_file_dir)
        self.tmp_dir = tempfile.mkdtemp(prefix=__name__ + '.')
        self.db_path = os.path.join(self.root, 'bot.db')
        connect(self.db_path)

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

    def save(self):
        self.logger.info('saving bot state')
        flush()

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

    @db_session
    def need_sticker_set(self, name):
        set_ = StickerSet.get(name=name)

        self.logger.info('need_sticker_set: name=%s res=%r', name, set_)

        if set_ is None:
            return True

        if self.sticker_set_update_interval >= 0:
            current_time = int(time.time())
            last_update = set_.last_update
            if current_time - last_update >= self.sticker_set_update_interval:
                return True

        return False

    @db_session
    def learn_sticker_set(self, data):
        if data is None:
            self.logger.info('not learning sticker set')
            return None

        current_time = int(time.time())

        self.logger.info(
            'learn_sticker_set: name=%s title=%s time=%s',
            data.name, data.title, current_time
        )

        set_ = StickerSet.get(name=data.name)
        if set_ is None:
            set_ = StickerSet(
                name=data.name,
                title=data.title,
                last_update=current_time
            )
            self.save()
        else:
            set_.name = data.name
            set_.title = data.title
            set_.last_update = current_time

        has_sticker = set(s.file_id for s in set_.stickers)
        for sticker in set_.stickers:
            if sticker.file_id not in has_sticker:
                Sticker(
                    set=set_,
                    file_id=sticker.file_id,
                    emoji=sticker.emoji
                )

        return set_

    @db_session
    def learn_user(self, data):
        return update_or_create(
            User, data.id, self.user_update_interval,
            first_name=data.first_name, last_name=data.last_name,
            username=data.username
        )

    @db_session
    def learn_user_phone(self, user_id, phone):
        ret = UserPhone.get(user=user_id, phone=phone)
        if ret is not None:
            return ret
        return UserPhone(
            user=user_id, phone=phone,
            timestamp=int(time.time())
        )

    @db_session
    def learn_contact(self, contact):
        if contact.user_id is None:
            return None
        get_or_create(
            User, contact.user_id,
            first_name=contact.first_name,
            last_name=contact.last_name
        )
        if contact.phone_number is not None:
            self.save()
            return self.learn_user_phone(
                contact.user_id,
                contact.phone_number
            )

    @db_session
    def learn_chat(self, chat):
        return update_or_create(
            Chat, chat.id, self.chat_update_interval,
            first_name=chat.first_name,
            last_name=chat.last_name,
            username=chat.username,
            title=chat.title,
            invite_link=chat.invite_link
        )

    @db_session
    def learn_message(self, message):
        if message.forward_from is not None:
            self.learn_user(message.forward_from)
        if message.forward_from_chat is not None:
            self.learn_chat(message.forward_from_chat)

        if message.contact is not None:
            return self.learn_contact(message.contact)

        msg_id = message.message_id
        chat_id = message.chat.id
        if message.from_user is None:
            user = None
        else:
            user = self.learn_user(message.from_user)

        timestamp = int(message.date.timestamp())
        text = message.text or message.caption
        file_id = None
        file_path = None
        file_name = None
        sticker_id = None

        try:
            ftype, file_id = get_file(message)
        except ValueError:
            pass
        else:
            file_path = os.path.join(ftype, get_message_filename(message))

        if message.sticker:
            sticker_id = message.sticker.file_id

        return Message(
            id_in_chat=msg_id,
            chat=chat_id, user=user,
            timestamp=timestamp, text=text, file_id=file_id,
            file_path=file_path, file_name=file_name,
            sticker_id=sticker_id
        )

    @db_session
    def learn_inline_query(self, query):
        timestamp = int(time.time())
        inline_query = query.query
        user = self.learn_user(query.from_user)
        return Message(
            id_in_chat=-1,
            chat=None, user=user,
            timestamp=timestamp, inline_query=inline_query
        )

    @db_session
    def learn_update(self, update):
        try:
            if update.effective_chat is not None:
                self.learn_chat(update.effective_chat)
            if update.effective_user is not None:
                self.learn_user(update.effective_user)
            if update.effective_message is not None:
                self.learn_message(update.effective_message)
            if update.inline_query is not None:
                self.learn_inline_query(update.inline_query)
        except Exception as ex:
            self.logger.error('learn_update: %r', ex)
            raise

    @db_session
    def learn_search_query(self, query, user, reset):
        query = query.strip().lower()
        user = self.learn_user(user)
        query_ = SearchQuery.get(query=query)
        if query_ is None:
            query_ = SearchQuery(query=query)
        if reset:
            query_.offset = 0
        else:
            query_.offset += 1
        SearchLog(user=user, query=query_, timestamp=int(time.time() * 1000))
        return query_.offset


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

        chat = Chat.from_tg(chat)
        for alias in chat.aliases:
            msg = re.sub(alias.regexp, alias.replace, msg, flags=re.I)

        if reply and self.RE_COMMAND_NO_ARGS.match(msg):
            msg = '%s %s' % (msg, reply)

        update.message.text = msg

    def get_chat_context(self, chat):
        if not isinstance(chat, Chat):
            chat = Chat.from_tg(chat)
        if chat.context is None:
            raise CommandError('generator context is not set')
        return self.context.get(chat.context)

    def get_chat_settings(self, chat):
        try:
            return self.get_chat_context(chat).settings
        except CommandError:
            return self.context.defaults

    def _need_reply(self, message):
        reply = False
        quote = False
        text = get_message_text(message)

        user = User.from_tg(message.from_user)
        permission = user.permission

        if permission <= P.BANNED:
            self.logger.info('ignored user: reply=False')
        elif message.chat.type == message.chat.PRIVATE:
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
                chat = Chat.from_tg(message.chat)
                trigger = chat.trigger
                if trigger is not None and re.search(trigger, text, re.I):
                    self.logger.info('trigger: reply=True')
                    quote = True
                    reply = True

        return reply, quote

    def random_text(self, update):
        chat = Chat.from_tg(update.message.chat)
        if chat.context is None:
            self.logger.info('no context')
            raise CommandError('generator context is not set')
        context = self.context.get(chat.context)
        try:
            return (
                context.random_text(chat.order, chat.reply_max_length),
                True
            )
        except KeyError as ex:
            self.logger.error(ex)
            return None

    def random_sticker(self):
        res = Sticker.select_random(1)
        if not res:
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

    @db_session
    def on_text(self, update):
        message = update.message
        reply, quote = self._need_reply(message)

        chat = Chat.from_tg(message.chat)

        context = self.context.get(chat.context)
        text = message.text
        res = None

        private = self.context.get_private(message.chat)

        self.logger.info('learn private')
        private.learn_text(text)

        if context is not None:
            if reply:
                try:
                    reply = context.reply_text(
                        text, chat.order,
                        chat.reply_max_length
                    )
                    self.logger.info('reply: "%s"', reply)
                    if reply:
                        res = (reply, quote)
                except KeyError as ex:
                    self.logger.error(ex)
            if chat.learn:
                self.logger.info('learn')
                context.learn_text(text)
        elif reply:
            self.logger.info('no context')
            raise CommandError('generator context is not set')

        return res

    @db_session
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

    @db_session
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

    @db_session
    def on_voice(self, update):
        message = update.message
        reply, quote = self._need_reply(message)
        if not reply:
            return None
        return 'on_voice', quote

    @db_session
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
