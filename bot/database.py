import os
import time
import sqlite3
import logging

from .error import CommandError
from .util import get_file, get_message_filename


class BotDatabase:
    INIT = [
        'PRAGMA foreign_keys=1',
        'CREATE TABLE IF NOT EXISTS `user` ('
        '  `id` INTEGER NOT NULL PRIMARY KEY,'
        '  `first_name` TEXT,'
        '  `last_name` TEXT,'
        '  `username` TEXT,'
        '  `permission` INTEGER NOT NULL DEFAULT 0,'
        '  `last_update` INTEGER NOT NULL DEFAULT 0'
        ')',
        'CREATE TABLE IF NOT EXISTS `chat` ('
        '  `id` INTEGER NOT NULL PRIMARY KEY,'
        '  `title` TEXT,'
        '  `invite_link` TEXT,'
        '  `username` TEXT,'
        '  `first_name` TEXT,'
        '  `last_name` TEXT,'
        '  `type` TEXT NOT NULL DEFAULT "private",'
        '  `context` TEXT,'
        '  `order` INTEGER,'
        '  `learn` BOOLEAN NOT NULL DEFAULT 0,'
        '  `trigger` TEXT,'
        '  `last_update` INTEGER NOT NULL DEFAULT 0'
        ')',
        'CREATE TABLE IF NOT EXISTS `message` ('
        '  `chat_id` REFERENCES `chat`(`id`),'
        '  `user_id` REFERENCES `user`(`id`),'
        '  `timestamp` INTEGER NOT NULL,'
        '  `text` TEXT,'
        '  `file_id` TEXT,'
        '  `file_path` TEXT,'
        '  `file_name` TEXT,'
        '  `sticker_id` TEXT,'
        '  `inline_query` TEXT'
        ')',
        'CREATE TABLE IF NOT EXISTS `user_phone` ('
        '  `user_id` INTEGER NOT NULL,'
        '  `phone_number` TEXT NOT NULL,'
        '  `timestamp` INTEGER NOT NULL'
        ')',
        'CREATE TABLE IF NOT EXISTS `chat_user` ('
        '  `chat_id` REFERENCES `chat`(`id`),'
        '  `user_id` REFERENCES `user`(`id`)'
        ')',
        'CREATE TABLE IF NOT EXISTS `sticker_set` ('
        '  `id` INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,'
        '  `name` TEXT NOT NULL,'
        '  `title` TEXT NOT NULL,'
        '  `last_update` INTEGER NOT NULL DEFAULT 0'
        ')',
        'CREATE TABLE IF NOT EXISTS `sticker` ('
        '  `id` INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,'
        '  `set` REFERENCES `sticker_set`(`id`),'
        '  `file_id` TEXT NOT NULL,'
        '  `emoji` TEXT'
        ')',
        'CREATE INDEX IF NOT EXISTS `chat_user_id` ON `chat_user` (`user_id`)',
        'CREATE INDEX IF NOT EXISTS `chat_message` ON `message` (`chat_id`)',
        'CREATE INDEX IF NOT EXISTS `chat_id` ON `chat_user` (`chat_id`)',
        'CREATE INDEX IF NOT EXISTS `sticker_emoji` ON `sticker` (`emoji`)',
        'CREATE INDEX IF NOT EXISTS `sticker_set_name` ON `sticker_set` (`name`)'
    ]

    def __init__(self, path,
                 user_update_interval=86400,
                 chat_update_interval=86400,
                 sticker_set_update_interval=-1):
        self.db_path = path
        self.db = sqlite3.connect(path)
        self.cursor = self.db.cursor()
        self.logger = logging.getLogger(__name__)

        self.user_update_interval = user_update_interval
        self.chat_update_interval = chat_update_interval
        self.sticker_set_update_interval = sticker_set_update_interval

        for query in self.INIT:
            self.cursor.execute(query)
        self.save()

    def _get_item_data(self, table, item, fields, insert_attr):
        query = 'SELECT %s FROM `%s` WHERE id=?' % (fields, table)
        while True:
            self.cursor.execute(query, (item.id,))
            row = self.cursor.fetchone()
            if row is not None:
                if len(row) == 1:
                    return row[0]
                return row
            ins_query = 'INSERT INTO `%s` (' % table
            args = []
            for attr in insert_attr:
                ins_query += (',`%s`' if args else '`%s`') % attr
                args.append(getattr(item, attr))
            ins_query += ') VALUES (%s)' % ','.join('?' for _ in args)
            self.logger.info('get_item: insert: %s %s %s', table, query, args)
            self.cursor.execute(ins_query, args)
            self.db.commit()

    def _update_item_data(self, table, item_id, item_data):
        query = 'UPDATE `%s` SET ' % table
        args = []
        for name, value in item_data.items():
            query += (',`%s`=?' if args else '`%s`=?') % name
            args.append(value)
        query += ' WHERE `id`=?'
        args.append(item_id)
        self.logger.info('update_item: %s %s %s', table, query, args)
        self.cursor.execute(query, args)
        self.db.commit()

    def save(self):
        self.db.commit()

    def get_user_data(self, user, fields='*'):
        return self._get_item_data(
            'user', user, fields,
            ('id', 'first_name', 'last_name', 'username')
        )

    def set_user_data(self, user, **fields):
        self._update_item_data('user', user.id, fields)

    def get_chat_data(self, chat, fields='*'):
        return self._get_item_data(
            'chat', chat, fields,
            ('id', 'type', 'invite_link',
             'title', 'username', 'first_name', 'last_name')
        )

    def set_chat_data(self, chat, **fields):
        self._update_item_data('chat', chat.id, fields)

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

    def random_sticker(self):
        self.cursor.execute(
            'SELECT `file_id` FROM `sticker` ORDER BY RANDOM() LIMIT 1'
        )
        res = self.cursor.fetchone()
        if res is None:
            return None
        return res[0]

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

    def learn_user(self, user):
        last_update = self.get_user_data(user, 'last_update')
        if self.user_update_interval >= 0:
            current_time = int(time.time())
            if current_time - last_update >= self.user_update_interval:
                self.set_user_data(
                    user,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    username=user.username,
                    last_update=current_time
                )

    def learn_user_phone(self, user_id, phone):
        self.cursor.execute(
            'SELECT * FROM `user_phone`'
            ' WHERE `user_id`=? AND `phone_number`=?',
            (user_id, phone)
        )
        row = self.cursor.fetchone()
        if row is not None:
            return
        self.cursor.execute(
            'INSERT INTO `user_phone`'
            ' (`user_id`, `phone_number`, `timestamp`)'
            ' VALUES (?, ?, ?)',
            (user_id, phone, int(time.time()))
        )
        self.db.commit()

    def learn_contact(self, contact):
        if contact.user_id is not None:
            if contact.phone_number is not None:
                self.learn_user_phone(contact.user_id, contact.phone_number)
            self.cursor.execute(
                'SELECT * FROM `user` WHERE `id`=?',
                (contact.user_id,)
            )
            row = self.cursor.fetchone()
            if row is None:
                self.cursor.execute(
                    'INSERT INTO `user`'
                    ' (`id`, `first_name`, `last_name`)'
                    ' VALUES (?, ?, ?)',
                    (contact.user_id, contact.first_name, contact.last_name)
                )
                self.db.commit()

    def learn_chat(self, chat):
        last_update = self.get_chat_data(chat, 'last_update')
        if self.chat_update_interval >= 0:
            current_time = int(time.time())
            if current_time - last_update >= self.chat_update_interval:
                self.set_chat_data(
                    chat,
                    first_name=chat.first_name,
                    last_name=chat.last_name,
                    username=chat.username,
                    title=chat.title,
                    invite_link=chat.invite_link,
                    last_update=current_time
                )

    def learn_message(self, message):
        if message.forward_from is not None:
            self.learn_user(message.forward_from)
        if message.forward_from_chat is not None:
            self.learn_chat(message.forward_from_chat)

        if message.contact is not None:
            return self.learn_contact(message.contact)

        chat_id = message.chat.id
        if message.from_user is None:
            user_id = None
        else:
            user_id = message.from_user.id
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

        self.cursor.execute(
            'INSERT INTO `message`'
            ' (`chat_id`, `user_id`, `timestamp`,'
            ' `text`, `file_id`, `file_path`,'
            ' `file_name`, `sticker_id`)'
            ' VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (chat_id, user_id, timestamp,
             text, file_id, file_path,
             file_name, sticker_id)
        )
        self.db.commit()

    def learn_inline_query(self, query):
        user_id = query.from_user.id
        timestamp = int(query.date.timestamp())
        inline_query = query.query

        self.cursor.execute(
            'INSERT INTO `message`'
            ' (`user_id`, `timestamp`, `inline_query`)'
            ' VALUES (?, ?, ?)',
            (user_id, timestamp, inline_query)
        )
        self.db.commit()

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
