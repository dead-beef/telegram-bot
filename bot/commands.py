import re
import logging

from uuid import uuid4
from functools import partial
from base64 import b64encode, b64decode

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
    CommandType as C
)


class BotCommands:
    HELP = (
        'commands:\n'
        '  /help - bot help\n'
        '  /helptags - list formatter tags\n'
        '  /helpemotes - list formatter emotes\n'
        '  /b64 <text> - encode base64\n'
        '  /b64d <base64> - decode base64\n'
        '  /delprivate - delete private context\n'
        '  /echo <text> - print text\n'
        '  /format <text> - format text\n'
        '  /setcontext - set generator context\n'
        '  /setlearn - set learning mode\n'
        '  /setorder - set markov chain order\n'
        '  /settings - print chat settings\n'
        '  /settrigger <regexp> - set trigger\n'
        '  /start - generate text\n'
        '  /sticker - send random sticker\n'
        '  /unsettrigger - remove trigger\n'
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
        return lambda *_: (self.state.random_sticker(), True)

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
