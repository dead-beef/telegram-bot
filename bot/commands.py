import re
import logging

from uuid import uuid4
from functools import partial
from base64 import b64encode, b64decode

import dice

from telegram import (
    ParseMode,
    InlineQueryResultArticle,
    InputTextMessageContent
)

from telegram.ext import (
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    Filters
)

from .error import CommandError
from .promise import Promise, PromiseType as PT
from .util import (
    get_command_args,
    command,
    update_handler,
    is_phone_number,
    reply_sticker_set,
    CommandType as C,
    Permission as P
)


class BotCommands:
    HELP = (
        '/help - bot help\n'
        '/helptags - list formatter tags\n'
        '/helpemotes - list formatter emotes\n'
        '\n'
        '/setcontext - set generator context\n'
        '/setlearn - set learning mode\n'
        '/setorder - set markov chain order\n'
        '/settings - print chat settings\n'
        '/settrigger <regexp> - set trigger\n'
        '/unsettrigger - remove trigger\n'
        '/delprivate - delete private context\n'
        '\n'
        '/b64 <text> - encode base64\n'
        '/b64d <base64> - decode base64\n'
        '/echo <text> - print text\n'
        '/format <text> - format text\n'
        '/roll <dice> - roll dice\n'
        '/start - generate text\n'
        '/sticker - send random sticker\n'
        '\n'
        '/getstickers - list sticker sets\n'
        '/getuser <+number> - get user by number\n'
        '/getusers - list users\n'
        '/stickerset <id> - send sticker set\n'
    )

    def __init__(self, bot):
        self.logger = logging.getLogger('bot.commands')
        self.state = bot.state
        self.formatter_tags = self.state.formatter.list_tags()
        self.formatter_emotes = self.state.formatter.list_emotes()
        self.queue = bot.queue
        self.stopped = bot.stopped
        dispatcher = bot.updater.dispatcher
        for field in dir(self):
            if field.startswith('cmd_'):
                cmd = field[4:]
                self.logger.info('init: command: /%s', cmd)
                handler = CommandHandler(cmd, getattr(self, field))
                dispatcher.add_handler(handler)
        dispatcher.add_handler(CallbackQueryHandler(
            self.callback_query
        ))
        dispatcher.add_handler(MessageHandler(
            Filters.command,
            self.unknown_command
        ))
        dispatcher.add_handler(MessageHandler(
            Filters.status_update,
            self.status_update
        ))

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
            learn = Promise.wrap(
                self.state.db.learn_user_phone,
                user_id, phone,
                ptype=PT.MANUAL
            )
            self.queue.put(learn)
            learn.catch(
                lambda ex: self.logger.error('learn_phone: %r', ex)
            ).wait()
        else:
            get = Promise.wrap(
                self.state.db.get_user_by_phone,
                phone,
                ptype=PT.MANUAL
            )
            self.queue.put(get)
            get.catch(
                lambda ex: self.logger.error('get: %r', ex)
            ).wait()
            user_id = get.value
            self.logger.info('get: %s', get.value)

        return user_id

    def _get_user_link(self, msg, phone):
        user_id = self._get_user_id(msg, phone)
        if user_id is None:
            return None
        return '[id{0} {1}](tg://user?id={0})'.format(user_id, phone)

    @update_handler
    def unknown_command(self, _, update):
        if update.message.chat.type == update.message.chat.PRIVATE:
            update.message.reply_text(
                'unknown command "%s"' % update.message.text,
                quote=True
            )

    @update_handler
    def callback_query(self, bot, update):
        msg = update.callback_query.message
        cmd = msg.text
        has_cmd = False

        for pattern in (r'^select\s+(.+)$', r'^([^\'"]+[^\s\'"]).*\?$'):
            match = re.match(pattern, msg.text, re.I)
            if match is not None:
                has_cmd = True
                cmd = 'cb_' + match.group(1).replace(' ', '_')
                break

        if has_cmd:
            try:
                cmd = getattr(self, cmd)
            except AttributeError:
                pass
            else:
                cmd(bot, update)
                return

        msg.edit_text(text='unknown command "%s"' % cmd)

    @update_handler
    def inline_query(self, _, update):
        query = update.inline_query.query
        results = [
            InlineQueryResultArticle(
                id=uuid4(),
                title='format',
                input_message_content=InputTextMessageContent(
                    self.state.formatter.format(query),
                    parse_mode=ParseMode.HTML
                )
            )
        ]
        update.inline_query.answer(results)

    @update_handler
    @command(C.REPLY_TEXT)
    def status_update(self, _, update):
        msg = update.message
        type_ = None
        if msg.new_chat_members:
            if any(user.id == self.state.id for user in msg.new_chat_members):
                type_ = 'add_self'
            elif any(user.is_bot for user in msg.new_chat_members):
                type_ = 'add_bot'
            else:
                type_ = 'add_user'
        elif msg.left_chat_member:
            if msg.left_chat_member.is_bot:
                if msg.left_chat_member.id != self.state.id:
                    type_ = 'remove_bot'
            else:
                type_ = 'remove_user'
        return partial(self.state.on_status_update, type_)

    @update_handler
    @command(C.REPLY_TEXT)
    def cmd_start(self, *_):
        return self.state.random_text

    @update_handler
    @command(C.REPLY_STICKER)
    def cmd_sticker(self, *_):
        return lambda *_: (self.state.db.random_sticker(), True)

    @update_handler
    @command(C.NONE)
    def cmd_help(self, _, update):
        update.message.reply_text(self.HELP)

    @update_handler
    @command(C.NONE)
    def cmd_helptags(self, _, update):
        update.message.reply_text(
            self.formatter_tags,
            parse_mode=ParseMode.HTML
        )

    @update_handler
    @command(C.NONE)
    def cmd_helpemotes(self, _, update):
        update.message.reply_text(self.formatter_emotes)

    @update_handler
    @command(C.NONE)
    def cmd_echo(self, bot, update):
        msg = get_command_args(update.message.text,
                               help='usage: /echo <text>')
        bot.send_message(chat_id=update.message.chat_id, text=msg)

    @update_handler
    @command(C.NONE)
    def cmd_roll(self, _, update):
        msg = get_command_args(update.message.text,
                               help='usage: /roll <dice>')
        roll = int(dice.roll(msg))
        update.message.reply_text(
            '<i>%s</i> → <b>%s</b>' % (msg, roll),
            quote=True,
            parse_mode=ParseMode.HTML
        )

    @update_handler
    @command(C.NONE)
    def cmd_format(self, _, update):
        msg = get_command_args(update.message.text,
                               help='usage: /format <text>')
        msg = self.state.formatter.format(msg)
        update.message.reply_text(msg, parse_mode=ParseMode.HTML)

    @update_handler
    @command(C.NONE)
    def cmd_b64(self, _, update):
        msg = get_command_args(update.message.text,
                               help='usage: /b64 <text>')
        msg = b64encode(msg.encode('utf-8')).decode('ascii')
        update.message.reply_text(msg, quote=True)

    @update_handler
    @command(C.NONE)
    def cmd_b64d(self, bot, update):
        msg = get_command_args(update.message.text,
                               help='usage: /b64d <base64>')
        msg = b64decode(msg.encode('utf-8'), validate=True).decode('utf-8')
        bot.send_message(chat_id=update.message.chat_id, text=msg)

    @update_handler
    @command(C.NONE, P.ADMIN)
    def cmd_getuser(self, _, update):
        msg = update.message
        num = get_command_args(update.message.text,
                               help='usage: /getuser <number>')
        if not is_phone_number(num):
            raise CommandError('invalid phone number')

        res = self._get_user_link(msg, num)
        if res is None:
            res = 'not found: ' + num
        msg.reply_text(res, parse_mode=ParseMode.MARKDOWN)

    @update_handler
    @command(C.NONE, P.ADMIN)
    def cmd_getstickers(self, _, update):
        msg = update.message
        get = Promise.wrap(
            self.state.db.get_sticker_sets,
            ptype=PT.MANUAL
        )
        self.queue.put(get)
        get.wait()
        sets = get.value
        if not sets:
            msg.reply_text('no sticker sets', quote=True)
        elif isinstance(sets, Exception):
            msg.reply_text(repr(sets), quote=True)
        else:
            res = '\n'.join(
                '{0}. [{1}](https://t.me/addstickers/{2})'.format(*set_)
                for set_ in sets
            )
            msg.reply_text(res, quote=True, parse_mode=ParseMode.MARKDOWN)

    @update_handler
    @command(C.NONE, P.ADMIN)
    def cmd_getusers(self, _, update):
        msg = update.message
        get = Promise.wrap(
            self.state.db.get_users,
            ptype=PT.MANUAL
        )
        self.queue.put(get)
        get.wait()
        users = get.value
        if not users:
            msg.reply_text('no users', quote=True)
        elif isinstance(users, Exception):
            msg.reply_text(repr(users), quote=True)
        else:
            res = '\n'.join(
                '{0}. ({5}) <a href="tg://user?id={1}">{1}</a> {2} {3} {4}'
                .format(
                    i + 1,
                    user[0],
                    user[1] or '&lt;no phone&gt;',
                    user[2] or '&lt;no name&gt;',
                    user[3] or '&lt;no username&gt;',
                    user[4]
                )
                for i, user in enumerate(users)
            )
            msg.reply_text(res, quote=True, parse_mode=ParseMode.HTML)

    @update_handler
    @command(C.NONE, P.ADMIN)
    def cmd_stickerset(self, _, update):
        msg = update.message
        set_id = get_command_args(msg.text, help='usage: /stickerset <id>')
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

    @update_handler
    @command(C.REPLY_TEXT)
    def cmd_settings(self, *_):
        return self.state.show_settings

    @update_handler
    @command(C.GET_OPTIONS)
    def cmd_setcontext(self, *_):
        return self.state.list_contexts

    @command(C.SET_OPTION)
    def cb_context(self, *_):
        return self.state.set_context

    @update_handler
    @command(C.GET_OPTIONS)
    def cmd_delprivate(self, *_):
        return self.state.confirm_delete_private_context

    @update_handler
    @command(C.SET_OPTION)
    def cb_delete_private_context(self, *_):
        return self.state.delete_private_context

    @update_handler
    @command(C.GET_OPTIONS)
    def cmd_setorder(self, *_):
        return self.state.list_orders

    @command(C.SET_OPTION)
    def cb_order(self, *_):
        return self.state.set_order

    @update_handler
    @command(C.GET_OPTIONS)
    def cmd_setlearn(self, *_):
        return self.state.list_learn_modes

    @command(C.SET_OPTION)
    def cb_learn_mode(self, *_):
        return self.state.set_learn_mode

    @update_handler
    @command(C.REPLY_TEXT)
    def cmd_settrigger(self, *_):
        return self.state.set_trigger

    @update_handler
    @command(C.REPLY_TEXT)
    def cmd_unsettrigger(self, *_):
        return self.state.remove_trigger
