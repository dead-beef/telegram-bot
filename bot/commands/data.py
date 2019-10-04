import re

from telegram import (
    ParseMode
)

from bot.error import CommandError
from bot.promise import Promise, PromiseType as PT
from bot.util import (
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

    @command(C.REPLY_TEXT, P.ROOT)
    def cmd_q(self, _, update):
        query = get_command_args(update.message, help='usage: /q <query>')
        return self.state.query_db(query)

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
        return self.state.list_users(update)

    @command(C.REPLY_TEXT_PAGINATED)
    def cb_users(self, _, update):
        return self.state.list_users(update)

    @command(C.NONE, P.ADMIN)
    def cmd_stickerset(self, _, update):
        msg = update.message
        set_id = get_command_args(msg, help='usage: /stickerset <id>')
        set_id = int(set_id)

        get = Promise.wrap(
            self.state.db.get_sticker_set,
            set_id,
            ptype=PT.MANUAL
        )
        self.queue.put(get)
        get.wait()
        stickers = get.value
        if not stickers:
            msg.reply_text('not found', quote=True)
        elif isinstance(stickers, Exception):
            msg.reply_text(repr(stickers), quote=True)
        else:
            self.state.run_async(reply_sticker_set, update, stickers)

    @command(C.REPLY_TEXT_PAGINATED)
    def cmd_getstickers(self, _, update):
        return self.state.list_sticker_sets(update)

    @command(C.REPLY_TEXT_PAGINATED)
    def cb_sticker_sets(self, _, update):
        return self.state.list_sticker_sets(update)
