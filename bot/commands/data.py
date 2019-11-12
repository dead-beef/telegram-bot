import re
import html

from pony.orm import desc
from telegram import (
    ParseMode
)

from bot.error import CommandError
from bot.models import db, get_page, User, UserPhone, StickerSet
from bot.util import (
    trunc,
    get_command_args,
    command,
    is_phone_number,
    reply_sticker_set,
    CommandType as C,
    Permission as P
)


class DataCommandMixin:
    RE_DICE = re.compile(r'^\s*([0-9d][-+0-9duwtfrF%hml^ov ]*)')
    RE_ALIAS = re.compile(r'^\s*(\S.*)=>\s*(\S.*)$')

    def __init__(self, bot):
        super().__init__(bot)
        self.help = self.help + (
            '\n'
            '/getstickers - list sticker sets\n'
            '/getuser <+number> - get user by number\n'
            '/getusers - list users\n'
            '/stickerset <id> - send sticker set\n'
            '/q <query> - sql query\n'
            '/qr <query> - sql query (read only)\n'
            '/qplot <query> - sql query plot (read only)\n'
        )

    def _get_user_id(self, msg, phone):
        user_id = None
        contact = msg.reply_contact(
            phone_number=phone,
            quote=False,
            first_name='user'
        )

        try:
            self.logger.info('contact %s', contact)
            user_id = contact.contact.user_id
        finally:
            contact.delete()

        if user_id is not None:
            self.state.db.learn_user_phone(user_id, phone)
        else:
            data = UserPhone.select(lambda d: d.phone == phone)[:1]
            if data:
                user_id = data[0].user.id
            self.logger.info('get: %s', user_id)

        return user_id

    def _get_user_link(self, msg, phone):
        user_id = self._get_user_id(msg, phone)
        if user_id is None:
            return None
        return '[id{0} {1}](tg://user?id={0})'.format(user_id, phone)

    @command(C.REPLY_TEXT, P.ROOT)
    def cmd_q(self, _, update):
        query = get_command_args(update.message, help='usage: /q <query>')
        db_ = db.get_connection()
        cursor = db_.cursor()
        cursor.execute(query)
        row_count = cursor.rowcount
        db_.commit()
        rows = cursor.fetchall()
        res = '\n'.join(' '.join(repr(col) for col in row) for row in rows)
        if not res:
            res = '%s rows affected' % row_count
        else:
            res = trunc(res)
        return res, True

    @command(C.NONE, P.USER_2)
    def cmd_qr(self, _, update):
        query = get_command_args(update.message, help='usage: /qr <query>')
        self.state.run_async(
            self._run_script, update,
            'query', [query],
            timeout=self.state.query_timeout
        )

    @command(C.NONE, P.USER_2)
    def cmd_qplot(self, _, update):
        query = get_command_args(update.message, help='usage: /qplot <query>')
        self.state.run_async(
            self._run_script, update,
            'qplot', ['-o', '{{TMP}}', query],
            return_image=True,
            timeout=self.state.query_timeout
        )

    @command(C.REPLY_TEXT, P.ADMIN)
    def cmd_getuser(self, _, update):
        msg = update.message
        num = get_command_args(update.message, help='usage: /getuser <number>')
        if not is_phone_number(num):
            raise CommandError('invalid phone number')

        res = self._get_user_link(msg, num)
        if res is None:
            res = 'not found: ' + num
        return res, True, ParseMode.MARKDOWN

    @command(C.REPLY_TEXT_PAGINATED)
    def cmd_getusers(self, _, update):
        page_size = 10

        if update.callback_query:
            page = int(update.callback_query.data)
        else:
            page = 1

        if update.effective_chat.type != update.effective_message.chat.PRIVATE:
            permission = 0
        else:
            permission = User.from_tg(update.effective_user).permission

        users = User.select().order_by(
            desc(User.permission),
            desc(User.last_update)
        )
        users, pages = get_page(users, page, page_size)
        if pages < 1:
            return 'no users', 1, 1, True

        offset = page_size * (page - 1)
        res = '\n'.join(
            '{0}. ({5}) <a href="tg://user?id={1}">{1}</a> {2} {3} {4}'
            .format(
                i,
                html.escape(user.name),
                html.escape(
                    (' '.join(data.phone for data in user.phones)
                     if permission >= P.ADMIN else None) or '<no phone>'
                ),
                html.escape(user.full_name or '<no name>'),
                html.escape(user.username or '<no username>'),
                user.permission
            )
            for i, user in enumerate(users, offset + 1)
        )
        res = 'users page %d / %d:\n\n%s' % (page, pages, res)
        return res, page, pages, False, ParseMode.HTML

    cb_users = cmd_getusers

    @command(C.NONE, P.ADMIN)
    def cmd_stickerset(self, _, update):
        msg = update.message
        set_id = get_command_args(msg, help='usage: /stickerset <id>')
        set_id = int(set_id)

        set_ = StickerSet.get(id=set_id)
        if not set_:
            msg.reply_text('not found', quote=True)
        else:
            stickers = list(set_.stickers)
            if not stickers:
                msg.reply_text('empty set', quote=True)
            else:
                self.state.run_async(reply_sticker_set, update, stickers)

    @command(C.REPLY_TEXT_PAGINATED)
    def cmd_getstickers(self, _, update):
        page_size = 25
        if update.callback_query:
            page = int(update.callback_query.data)
        else:
            page = 1
        sets, pages = get_page(StickerSet.select(), page, page_size)
        if pages < 1:
            return 'no sticker sets', 1
        res = '\n'.join(
            '{0}. [{1}](https://t.me/addstickers/{2})'.format(
                set_.id, set_.title, set_.name
            )
            for set_ in sets
        )
        res = 'sticker sets page %d / %d:\n%s' % (page, pages, res)
        return res, page, pages, False, ParseMode.MARKDOWN

    cb_sticker_sets = cmd_getstickers
