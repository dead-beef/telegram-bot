import re
from pony.orm import delete

from bot.models import Alias, Chat
from bot.error import CommandError
from bot.util import (
    strip_command,
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
            '/unsetcontext - unset generator context\n'
            '/unsettrigger - remove trigger\n'
            '/delprivate - delete private context\n'
        )

    @command(C.REPLY_TEXT)
    def cmd_alias(self, _, update):
        chat = Chat.from_tg(update.message.chat)
        ret = '\n'.join(
            '%s. %s → %s' % (alias.id, alias.regexp, alias.replace)
            for alias in chat.aliases
        )
        if not ret:
            ret = 'no aliases'
        return ret, True

    @command(C.REPLY_TEXT, P.ADMIN, P.USER)
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
        chat = Chat.from_tg(update.message.chat)
        Alias(chat=chat, regexp=expr, replace=repl)
        return 'done'

    @command(C.REPLY_TEXT, P.ADMIN, P.USER)
    def cmd_adel(self, _, update):
        id_ = get_command_args(update.message, help='usage: /adel <id>')
        id_ = int(id_)
        alias = Alias.get(id=id_)
        if alias is not None:
            alias.delete()
            return 'done', True
        return 'not found', True

    @command(C.REPLY_TEXT, P.ADMIN, P.USER)
    def cmd_aclear(self, _, update):
        chat = Chat.from_tg(update.message.chat)
        delete(a for a in Alias if a.chat == chat)
        return 'done'

    @command(C.REPLY_TEXT)
    def cmd_settings(self, _, update):
        chat = Chat.from_tg(update.message.chat)
        reply = (
            'settings:\n'
            '    context: %s\n'
            '    markov chain order: %s\n'
            '    learn: %s\n'
            '    trigger: %s\n'
            '    max reply length: %s\n'
        ) % (
            chat.context,
            chat.order,
            bool(chat.learn),
            chat.trigger,
            chat.reply_max_length
        )
        return reply

    @command(C.REPLY_TEXT, P.ADMIN, P.USER)
    def cmd_unsetcontext(self, _, update):
        chat = update.message.chat

        self.logger.info('unset_context %s', chat.id)
        chat = Chat.from_tg(chat)

        prev_context = chat.context
        prev_order = chat.order
        prev_learn = chat.learn

        chat.context = None
        chat.order = 0
        chat.learn = False

        return 'context: %s -> %s\norder: %s -> %s\nlearn: %s -> %s' % (
            prev_context, chat.context,
            prev_order, chat.order,
            bool(prev_learn), bool(chat.learn)
        )

    @command(C.GET_OPTIONS, P.ADMIN, P.USER)
    def cmd_setcontext(self, _, update):
        ret = self.state.context.list(update.message.chat.id)
        if ret:
            return 'select context', ret
        raise CommandError('no context available')

    @command(C.SET_OPTION, P.ADMIN, P.USER)
    def cb_context(self, _, update):
        query = update.callback_query
        chat = query.message.chat
        name = query.data

        self.logger.info('set_context %s %s', chat.id, name)
        chat = Chat.from_tg(chat)
        prev_context = chat.context
        prev_order = chat.order
        prev_learn = chat.learn

        if name == 'new private context':
            self.logger.info('creating private context %s', chat.id)
            context = self.state.context.get_private(chat)
            name = context.name
            learn = True
        else:
            context = self.state.context.get(name)
            learn = prev_learn

        if not context.is_writable:
            learn = False

        orders = context.get_orders()
        if prev_order not in orders:
            order = next(iter(orders))
        else:
            order = prev_order

        chat.context = name
        chat.order = order
        chat.learn = learn

        return 'context: %s -> %s\norder: %s -> %s\nlearn: %s -> %s' % (
            prev_context, name,
            prev_order, order,
            bool(prev_learn), bool(learn)
        )

    @command(C.GET_OPTIONS, P.ROOT, P.USER)
    def cmd_delprivate(self, _, update):
        chat = update.message.chat
        if not self.state.context.has_private(chat):
            raise CommandError('context "%s" does not exist' % chat.id)
        return 'delete private context "%s"?' % chat.id, ['yes', 'no']

    @command(C.SET_OPTION, P.ROOT, P.USER)
    def cb_delete_private_context(self, _, update):
        query = update.callback_query
        chat = query.message.chat
        if query.data.lower() == 'yes':
            chat = Chat.from_tg(chat)
            context = chat.context
            if context == str(chat.id):
                chat.context = None
            self.state.context.delete_private(chat)
            return 'deleted private context "%s"' % chat.id
        return 'cancelled'

    @command(C.GET_OPTIONS, P.ADMIN, P.USER)
    def cmd_setorder(self, _, update):
        context = self.state.get_chat_context(update.message.chat)
        return 'select order', context.get_orders()

    @command(C.SET_OPTION, P.ADMIN, P.USER)
    def cb_order(self, _, update):
        query = update.callback_query
        chat = query.message.chat
        order = int(query.data)
        self.logger.info('set_order %s %s', chat.id, order)
        chat = Chat.from_tg(chat)
        context = self.state.get_chat_context(chat)
        if order not in context.get_orders():
            raise CommandError('invalid order: %s: not in %s' % (
                order, context.get_orders()
            ))
        prev = chat.order
        chat.order = order
        return 'order: %s -> %s' % (prev, order)

    @command(C.GET_OPTIONS, P.ADMIN, P.USER)
    def cmd_setlearn(self, _, update):
        context = self.state.get_chat_context(update.message.chat)
        if not context.is_writable:
            raise CommandError('context "%s" is read only' % context.name)
        return 'select learn mode', ['on', 'off']

    @command(C.SET_OPTION, P.ADMIN, P.USER)
    def cb_learn_mode(self, _, update):
        query = update.callback_query
        chat = Chat.from_tg(query.message.chat)
        learn = query.data.lower() == 'on'
        self.logger.info('set_learn %s %s', chat.id, learn)
        context = self.state.get_chat_context(chat)
        if learn and not context.is_writable:
            raise CommandError('context %s is read only' % context)
        prev = bool(chat.learn)
        chat.learn = int(learn)
        return 'learn: %s -> %s' % (prev, learn)

    @command(C.REPLY_TEXT, P.ADMIN, P.USER)
    def cmd_settrigger(self, _, update):
        message = update.message
        expr = strip_command(message.text)
        if not expr:
            raise CommandError('usage: /settrigger <regexp>')
        else:
            try:
                re.compile(expr)
            except re.error as ex:
                raise CommandError(ex)
        chat = Chat.from_tg(message.chat)
        prev = chat.trigger
        chat.trigger = expr
        return 'trigger: %s -> %s' % (prev, expr)

    @command(C.REPLY_TEXT, P.ADMIN, P.USER)
    def cmd_setreplylength(self, _, update):
        message = update.message
        length = strip_command(message.text)
        if not length:
            raise CommandError('usage: /setreplylength <number>')
        try:
            length = max(8, min(int(length), 256))
        except ValueError as ex:
            raise CommandError(ex)
        chat = Chat.from_tg(message.chat)
        prev = chat.reply_max_length
        chat.reply_max_length = length
        return 'max reply length: %d -> %d' % (prev, length)

    @command(C.REPLY_TEXT, P.ADMIN, P.USER)
    def cmd_unsettrigger(self, _, update):
        chat = Chat.from_tg(update.message.chat)
        prev = chat.trigger
        chat.trigger = None
        return 'trigger: %s -> None' % prev
