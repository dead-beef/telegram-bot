import os
import time
import math
import logging

try:
    import pysqlite3 as sqlite3
except ImportError:
    import sqlite3

from .error import CommandError
from .util import get_file, get_message_filename, Permission as P


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
        '  `reply_max_length` INTEGER NOT NULL DEFAULT 64,'
        '  `trigger` TEXT,'
        '  `last_update` INTEGER NOT NULL DEFAULT 0'
        ')',
        'CREATE TABLE IF NOT EXISTS `message` ('
        '  `id` INTEGER NOT NULL DEFAULT -1,'
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
        'CREATE TABLE IF NOT EXISTS `alias` ('
        '  `id` INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,'
        '  `chat_id` REFERENCES `chat`(`id`),'
        '  `regexp` TEXT NOT NULL,'
        '  `replace` TEXT NOT NULL'
        ')',
        'CREATE TABLE IF NOT EXISTS `sticker_set` ('
        '  `id` INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,'
        '  `name` TEXT NOT NULL,'
        '  `title` TEXT NOT NULL,'
        '  `last_update` INTEGER NOT NULL DEFAULT 0,'
        '  UNIQUE (`name`)'
        ')',
        'CREATE TABLE IF NOT EXISTS `sticker` ('
        '  `id` INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,'
        '  `set_id` REFERENCES `sticker_set`(`id`),'
        '  `file_id` TEXT NOT NULL,'
        '  `emoji` TEXT,'
        '  UNIQUE (`set_id`, `file_id`)'
        ')',
        'CREATE TABLE IF NOT EXISTS `search_query` ('
        '  `id` INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,'
        '  `query` TEXT NOT NULL,'
        '  `offset` INTEGER NOT NULL DEFAULT 0'
        ')',
        'CREATE TABLE IF NOT EXISTS `search_log` ('
        '  `id` INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,'
        '  `search_query_id` REFERENCES `search_query`(`id`),'
        '  `user_id` REFERENCES `user`(`id`),'
        '  `timestamp` INTEGER NOT NULL DEFAULT 0'
        ')',
        'CREATE TABLE IF NOT EXISTS `search_log` ('
        '  `id` INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,'
        '  `search_query_id` REFERENCES `search_query`(`id`),'
        '  `user_id` REFERENCES `user`(`id`),'
        '  `timestamp` INTEGER NOT NULL DEFAULT 0'
        ')',
        'CREATE INDEX IF NOT EXISTS `chat_alias` ON `alias` (`chat_id`)',
        'CREATE INDEX IF NOT EXISTS `chat_user_id` ON `chat_user` (`user_id`)',
        'CREATE INDEX IF NOT EXISTS `chat_message` ON `message` (`chat_id`)',
        'CREATE INDEX IF NOT EXISTS `chat_id` ON `chat_user` (`chat_id`)',
        'CREATE INDEX IF NOT EXISTS `sticker_emoji` ON `sticker` (`emoji`)',
        'CREATE INDEX IF NOT EXISTS `sticker_set_name` ON `sticker_set` (`name`)',
        'CREATE INDEX IF NOT EXISTS `search_log_query` ON `search_log` (`search_query_id`)',
        'CREATE INDEX IF NOT EXISTS `search_log_user` ON `search_log` (`user_id`)'
    ]

    MERGE = [
        'INSERT OR REPLACE INTO `user`'
        ' SELECT `new`.*'
        ' FROM `to_merge`.`user` `new`'
        ' LEFT JOIN `user` `old`'
        ' ON `new`.`id`=`old`.`id`'
        ' WHERE `old`.`id` IS NULL OR `new`.`last_update` > `old`.`last_update`',

        'INSERT OR REPLACE INTO `user_phone`'
        ' SELECT `new`.*'
        ' FROM `to_merge`.`user_phone` `new`'
        ' LEFT JOIN `user_phone` `old`'
        ' ON `new`.`user_id`=`old`.`user_id`'
        ' AND `new`.`phone_number`=`old`.`phone_number`'
        ' WHERE `old`.`user_id` IS NULL'
        ' OR `new`.`timestamp` > `old`.`timestamp`',

        'INSERT OR REPLACE INTO `chat`'
        ' SELECT `new`.*'
        ' FROM `to_merge`.`chat` `new`'
        ' LEFT JOIN `chat` `old`'
        ' ON `new`.`id`=`old`.`id`'
        ' WHERE `old`.`id` IS NULL'
        ' OR `new`.`last_update` > `old`.`last_update`',

        'INSERT OR REPLACE INTO `message`'
        ' SELECT `new`.*'
        ' FROM `to_merge`.`message` `new`'
        ' WHERE `timestamp` > (SELECT MAX(`timestamp`) FROM `message`)',

        #'INSERT OR REPLACE INTO `sticker_set`'
        #' SELECT `new`.*'
        #' FROM `to_merge`.`sticker_set` `new`'
        #' LEFT JOIN `sticker_set` `old`'
        #' ON `new`.`id`=`old`.`id`'
        #' WHERE `old`.`id` IS NULL'
        #' OR `new`.`last_update` > `old`.`last_update`',

        #'INSERT OR REPLACE INTO `sticker`'
        #' SELECT `new`.*'
        #' FROM `to_merge`.`sticker` `new`',

        'INSERT INTO `search_query` (`query`)'
        ' SELECT `new`.`query`'
        ' FROM `to_merge`.`search_query` `new`'
        ' LEFT JOIN `search_query` `old`'
        ' ON `new`.`query` = `old`.`query`'
        ' WHERE `old`.`id` IS NULL',

        'INSERT INTO `search_log` (`search_query_id`, `user_id`, `timestamp`)'
        ' SELECT `sq`.`id`, `new`.`user_id`, `new`.`timestamp`'
        ' FROM `to_merge`.`search_log` `new`'
        ' LEFT JOIN `to_merge`.`search_query` `new_sq`'
        ' ON `new`.`search_query_id` = `new_sq`.`id`'
        ' LEFT JOIN `search_query` `sq`'
        ' ON `new_sq`.`query` = `sq`.`query`'
        ' WHERE `new`.`timestamp` > (SELECT MAX(`timestamp`) FROM `search_log`)'
    ]

    def __init__(self, path,
                 user_update_interval=86400,
                 chat_update_interval=86400,
                 sticker_set_update_interval=86400):
        self.logger = logging.getLogger(__name__)
        self.db_path = path
        self.db = sqlite3.connect(path)
        self.cursor = self.db.cursor()

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

    def merge(self, db):
        self.cursor.execute('ATTACH ? AS to_merge', (db,))
        self.cursor.execute('BEGIN')
        try:
            for cmd in self.MERGE:
                self.cursor.execute(cmd)
        except BaseException as ex:
            self.cursor.execute('ROLLBACK')
            raise type(ex)(cmd, ex)
        else:
            self.cursor.execute('COMMIT')
        finally:
            self.cursor.execute('DETACH to_merge')

    def get_user_data(self, user, fields='*'):
        return self._get_item_data(
            'user', user, fields,
            ('id', 'first_name', 'last_name', 'username')
        )

    def set_user_data(self, user, **fields):
        self._update_item_data('user', user.id, fields)

    def get_user_by_phone(self, phone):
        self.cursor.execute(
            'SELECT `user_id` FROM `user_phone`'
            'WHERE `phone_number`=? ORDER BY `timestamp` DESC LIMIT 1',
            (phone,)
        )
        row = self.cursor.fetchone()
        if row is not None:
            row = row[0]
        return row

    def get_chat_data(self, chat, fields='*'):
        return self._get_item_data(
            'chat', chat, fields,
            ('id', 'type', 'invite_link',
             'title', 'username', 'first_name', 'last_name')
        )

    def set_chat_data(self, chat, **fields):
        self._update_item_data('chat', chat.id, fields)

    def get_chat_aliases(self, chat):
        self.cursor.execute(
            'SELECT `id`, `regexp`, `replace` FROM `alias`'
            ' WHERE `chat_id`=?',
            (chat.id,)
        )
        return self.cursor.fetchall()

    def add_chat_alias(self, chat, regexp, replace):
        self.cursor.execute(
            'INSERT INTO `alias`'
            ' (`chat_id`, `regexp`, `replace`) VALUES (?, ?, ?)',
            (chat.id, regexp, replace)
        )
        return self.cursor.fetchall()

    def edit_chat_alias(self, chat, alias_id, regexp, replace):
        self.cursor.execute(
            'UPDATE `alias` SET `regexp`=?, `replace`=?'
            ' WHERE `id`=? AND `chat_id`=?',
            (regexp, replace, alias_id, chat.id)
        )

    def delete_chat_alias(self, chat, alias_id=None):
        if alias_id is None:
            self.cursor.execute(
                'DELETE FROM `alias` WHERE `chat_id`=?',
                (chat.id,)
            )
        else:
            self.cursor.execute(
                'DELETE FROM `alias` WHERE `id`=? AND `chat_id`=?',
                (alias_id, chat.id)
            )

    def get_sticker_sets(self, page, page_size):
        page = max(page - 1, 0)
        self.cursor.execute('SELECT COUNT(*) FROM `sticker_set`')
        pages = math.ceil(self.cursor.fetchone()[0] / page_size)
        self.cursor.execute(
            'SELECT `id`, `title`, `name`'
            ' FROM `sticker_set`'
            ' ORDER BY `id` ASC'
            ' LIMIT ? OFFSET ?',
            (page_size, page * page_size)
        )
        return self.cursor.fetchall(), pages

    def get_sticker_set(self, set_id):
        self.cursor.execute(
            'SELECT `file_id`'
            ' FROM `sticker` WHERE `set_id`=?'
            ' ORDER BY `id` ASC',
            (set_id,)
        )
        return self.cursor.fetchall()

    def get_users(self, page, page_size, permission):
        page = max(page - 1, 0)
        self.cursor.execute('SELECT COUNT(*) FROM `user`')
        pages = math.ceil(self.cursor.fetchone()[0] / page_size)
        if permission >= P.ADMIN:
            query = (
                'SELECT'
                '  `user`.`id`,'
                '  `user_phone`.`phone_number`,'
                '  COALESCE(`user`.`first_name` || " " || `user`.`last_name`,'
                '           `user`.`first_name`),'
                '  "@" || `user`.`username`,'
                '  `user`.`permission`'
                ' FROM `user`'
                ' LEFT JOIN `user_phone` ON `user`.`id`=`user_phone`.`user_id`'
                ' ORDER BY'
                '  `user`.`permission` DESC,'
                '  `user`.`last_update` DESC,'
                '  `user_phone`.`timestamp` DESC'
                ' LIMIT ? OFFSET ?'
            )
        else:
            query = (
                'SELECT'
                '  `id`, "",'
                '  COALESCE(`user`.`first_name` || " " || `user`.`last_name`,'
                '           `user`.`first_name`),'
                '  "@" || `username`,'
                '  `permission`'
                ' FROM `user`'
                ' ORDER BY'
                '  `user`.`permission` DESC,'
                '  `user`.`last_update` DESC'
                ' LIMIT ? OFFSET ?'
            )
        self.cursor.execute(
            query,
            (page_size, page * page_size)
        )
        return self.cursor.fetchall(), pages

    def get_search_log(self, page, page_size):
        page = max(page - 1, 0)
        self.cursor.execute('SELECT COUNT(*) FROM `search_log`')
        pages = math.ceil(self.cursor.fetchone()[0] / page_size)
        self.cursor.execute(
            'SELECT `search_query`.`query`,'
            '        COALESCE(`user`.`username`,'
            '                 `user`.`first_name`,'
            '                 `user`.`last_name`)'
            ' FROM `search_log`'
            '  LEFT JOIN `search_query`'
            '   ON `search_log`.`search_query_id`'
            '       = `search_query`.`id`'
            '  LEFT JOIN `user`'
            '   ON `search_log`.`user_id` = `user`.`id`'
            ' ORDER BY `search_log`.`id` DESC'
            ' LIMIT ? OFFSET ?',
            (page_size, page * page_size)
        )
        return self.cursor.fetchall(), pages

    def get_search_stats(self, page, page_size):
        page = max(page - 1, 0)
        self.cursor.execute('SELECT COUNT(*) FROM `search_query`')
        pages = math.ceil(self.cursor.fetchone()[0] / page_size)
        self.cursor.execute(
            'SELECT `search_query`.`query`,'
            '       COUNT(`search_log`.`id`) as `count`'
            ' FROM `search_query`'
            '  LEFT JOIN `search_log`'
            '   ON `search_query`.`id` = `search_log`.`search_query_id`'
            ' GROUP BY `search_query`.`id`'
            ' ORDER BY `count` DESC, `search_query`.`query` ASC'
            ' LIMIT ? OFFSET ?',
            (page_size, page * page_size)
        )
        return self.cursor.fetchall(), pages

    def need_sticker_set(self, name):
        self.cursor.execute(
            'SELECT `last_update` FROM `sticker_set` WHERE `name`=?',
            (name,)
        )
        res = self.cursor.fetchone()
        self.logger.info('need_sticker_set: name=%s res=%r', name, res)
        if res is None:
            return True
        if self.sticker_set_update_interval >= 0:
            last_update = res[0]
            current_time = int(time.time())
            if current_time - last_update >= self.sticker_set_update_interval:
                return True
        return False

    def random_sticker(self):
        self.cursor.execute(
            'SELECT `file_id` FROM `sticker` ORDER BY RANDOM() LIMIT 1'
        )
        res = self.cursor.fetchone()
        if res is None:
            return None
        return res[0]

    def learn_sticker_set(self, set_):
        if set_ is None:
            self.logger.info('not learning sticker set')
            return

        current_time = int(time.time())

        self.logger.info(
            'learn_sticker_set: name=%s title=%s time=%s',
            set_.name, set_.title, current_time
        )

        self.cursor.execute(
            'SELECT `id` FROM `sticker_set` WHERE `name`=?',
            (set_.name,)
        )
        row = self.cursor.fetchone()

        if row is None:
            self.cursor.execute(
                'INSERT INTO `sticker_set` (`name`, `title`, `last_update`)'
                ' VALUES (?, ?, ?)',
                (set_.name, set_.title, current_time)
            )
            self.cursor.execute(
                'SELECT `id` FROM `sticker_set` WHERE `name`=?',
                (set_.name,)
            )
            set_id = self.cursor.fetchone()[0]
        else:
            set_id = row[0]
            self.cursor.execute(
                'UPDATE `sticker_set`'
                ' SET `name`=?, `title`=?, `last_update`=?'
                ' WHERE `id`=?',
                (set_.name, set_.title, current_time, set_id)
            )

        for sticker in set_.stickers:
            self.cursor.execute(
                'INSERT OR REPLACE'
                ' INTO `sticker` (`set_id`, `file_id`, `emoji`)'
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

        msg_id = message.message_id
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
            ' (`id`, `chat_id`, `user_id`, `timestamp`,'
            ' `text`, `file_id`, `file_path`,'
            ' `file_name`, `sticker_id`)'
            ' VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (msg_id, chat_id, user_id, timestamp,
             text, file_id, file_path,
             file_name, sticker_id)
        )
        self.db.commit()

    def learn_inline_query(self, query):
        user_id = query.from_user.id
        timestamp = int(time.time())
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

    def learn_search_query(self, query, user, reset):
        query = query.strip().lower()
        self.learn_user(user)
        while True:
            self.cursor.execute(
                'SELECT `id`, `offset` FROM `search_query` WHERE `query`=?',
                (query,)
            )
            row = self.cursor.fetchone()
            if row is None:
                self.cursor.execute(
                    'INSERT INTO `search_query`(`query`) VALUES(?)',
                    (query,)
                )
            else:
                query_id, offset = row
                break
        if reset:
            offset = 0
        self.cursor.execute(
            'UPDATE `search_query` SET `offset`=?  WHERE `id`=?',
            (offset + 1, query_id)
        )
        self.cursor.execute(
            'INSERT INTO `search_log`'
            ' (`search_query_id`, `user_id`, `timestamp`)'
            ' VALUES(?, ?, ?)',
            (query_id, user.id, int(time.time() * 1000))
        )
        self.db.commit()
        return offset
