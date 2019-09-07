import re

from bot.util import (
    get_command_args,
    command,
    CommandType as C,
    Permission as P
)


class SettingsCommandMixin:
    RE_ALIAS = re.compile(r'^\s*(\S.*)=>\s*(\S.*)$')

    def __init__(self, bot):
        super().__init__(bot)
        self.help = self.help + (
            '\n'
            '/alias - list aliases\n'
            '/aadd <regexp> => <string> - add alias\n'
            '/adel <id> - delete alias\n'
            '/aclear - delete all aliases\n'
            '\n'
            '/setcontext - set generator context\n'
            '/setlearn - set learning mode\n'
            '/setorder - set markov chain order\n'
            '/settings - print chat settings\n'
            '/settrigger <regexp> - set trigger\n'
            '/setreplylength <words> - set max reply length\n'
            '/unsettrigger - remove trigger\n'
            '/delprivate - delete private context\n'
        )

    @command(C.REPLY_TEXT)
    def cmd_alias(self, _, update):
        ret = '\n'.join(
            '%s. %s → %s' % (id_, expr, repl)
            for id_, expr, repl
            in self.state.db.get_chat_aliases(update.message.chat)
        )
        if not ret:
            ret = 'no aliases'
        return ret, True

    @command(C.REPLY_TEXT, P.ADMIN)
    def cmd_aadd(self, _, update):
        help_ = 'usage: /aadd <regexp>=<string>'
        args = get_command_args(update.message, help=help_)
        match = self.RE_ALIAS.match(args)
        if match is None:
            return help_
        expr, repl = match.groups()
        expr = expr.strip()
        repl = repl.strip()
        re.compile(expr)
        self.state.db.add_chat_alias(update.message.chat, expr, repl)
        return '%s rows affected' % self.state.db.cursor.rowcount

    @command(C.REPLY_TEXT, P.ADMIN)
    def cmd_adel(self, _, update):
        id_ = get_command_args(update.message, help='usage: /adel <id>')
        id_ = int(id_)
        self.state.db.delete_chat_alias(update.message.chat, id_)
        return '%s rows affected' % self.state.db.cursor.rowcount

    @command(C.REPLY_TEXT, P.ADMIN)
    def cmd_aclear(self, _, update):
        self.state.db.delete_chat_alias(update.message.chat, None)
        return '%s rows affected' % self.state.db.cursor.rowcount

    @command(C.REPLY_TEXT)
    def cmd_settings(self, _, update):
        return self.state.show_settings(update)

    @command(C.GET_OPTIONS)
    def cmd_setcontext(self, _, update):
        return self.state.list_contexts(update)

    @command(C.SET_OPTION)
    def cb_context(self, *_):
        return self.state.set_context

    @command(C.GET_OPTIONS)
    def cmd_delprivate(self, _, update):
        return self.state.confirm_delete_private_context(update)

    @command(C.SET_OPTION)
    def cb_delete_private_context(self, *_):
        return self.state.delete_private_context

    @command(C.GET_OPTIONS)
    def cmd_setorder(self, _, update):
        return self.state.list_orders(update)

    @command(C.SET_OPTION)
    def cb_order(self, *_):
        return self.state.set_order

    @command(C.GET_OPTIONS)
    def cmd_setlearn(self, _, update):
        return self.state.list_learn_modes(update)

    @command(C.SET_OPTION)
    def cb_learn_mode(self, *_):
        return self.state.set_learn_mode

    @command(C.REPLY_TEXT)
    def cmd_settrigger(self, _, update):
        return self.state.set_trigger(update)

    @command(C.REPLY_TEXT)
    def cmd_setreplylength(self, *_):
        return self.state.set_reply_length

    @command(C.REPLY_TEXT)
    def cmd_unsettrigger(self, _, update):
        return self.state.remove_trigger(update)
