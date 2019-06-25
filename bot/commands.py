import re
import math
import html
import logging

from uuid import uuid4
from itertools import islice
from functools import partial
from base64 import b64encode, b64decode

import dice

from telegram import (
    ChatAction,
    TelegramError,
    ParseMode,
    InlineQueryResultArticle,
    InputTextMessageContent,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    Filters
)
from telegram.error import BadRequest

from .safe_eval import safe_eval
from .error import CommandError
from .promise import Promise, PromiseType as PT
from .util import (
    remove_control_chars,
    get_command_args,
    get_user_name,
    command,
    update_handler,
    download_file,
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
        '/setreplylength <words> - set max reply length\n'
        '/unsettrigger - remove trigger\n'
        '/delprivate - delete private context\n'
        '\n'
        '/b64 <text> - encode base64\n'
        '/b64d <base64> - decode base64\n'
        '/echo <text> - print text\n'
        '/format <text> - format text\n'
        '/eval <expression> - evaluate expression\n'
        '/roll <dice> - roll dice\n'
        '/pic <query> - image search\n'
        '/piclog - show image search log\n'
        '/picstats - show image search stats\n'
        '/start - generate text\n'
        '/image - generate image\n'
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

    def _search(self, update, query):
        if update.callback_query:
            user = update.callback_query.from_user
        else:
            user = update.message.from_user

        learn = Promise.wrap(
            self.state.db.learn_search_query,
            query, user,
            ptype=PT.MANUAL
        )
        self.state.bot.queue.put(learn)

        chat_id = update.effective_chat.id
        if update.message:
            reply_to = update.message.message_id
            bot = update.message.bot
        else:
            reply_to = None
            bot = update.callback_query.bot

        try:
            bot.send_chat_action(chat_id, ChatAction.UPLOAD_PHOTO)
        except TelegramError as ex:
            self.logger.error('send_chat_action: %r', ex)

        try:
            res = self.state.search(query)
        except Exception as ex:
            bot.send_message(
                chat_id, repr(ex), quote=True,
                reply_to_message_id=reply_to
            )
            return
        else:
            keyboard = [[
                InlineKeyboardButton(
                    '\U0001f517 %d' % (res.offset + 1),
                    url=res.url
                ),
                InlineKeyboardButton('next', callback_data='pic')
            ]]
            for url in (res.image, res.thumbnail, None):
                try:
                    self.logger.info('%r %r', query, url)
                    if url is None:
                        bot.send_message(
                            chat_id,
                            '(bad request)\n%s\n%s\n\n%s' % (
                                res.image, res.url, query
                            ),
                            quote=True,
                            reply_to_message_id=reply_to
                        )
                    else:
                        bot.send_photo(
                            chat_id,
                            url,
                            caption=query,
                            quote=True,
                            reply_to_message_id=reply_to,
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                    return
                except BadRequest as ex:
                    self.logger.info('image post failed: %r: %r', res, ex)

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
        cmd = None
        has_cmd = False

        if msg.text:
            for pattern in (r'^select\s+(.+)$',
                            r'^(.+[^\s])\s+page',
                            r'^([^\'"]+[^\s\'"]).*\?$'):
                match = re.match(pattern, msg.text, re.I)
                if match is not None:
                    has_cmd = True
                    cmd = 'cb_' + match.group(1).replace(' ', '_')
                    break

        match = re.match(r'^([a-z_]+)\s*(.*)', update.callback_query.data)
        if match is not None:
            cmd_ = 'cb_' + match.group(1)
            if hasattr(self, cmd_):
                cmd = cmd_
                has_cmd = True
                update.callback_query.data = match.group(2)

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
    @command(C.NONE)
    def cmd_pic(self, _, update):
        query = get_command_args(update.message, help='usage: /pic <query>')
        query = remove_control_chars(query).replace('\n', ' ')
        self.state.run_async(self._search, update, query)

    @update_handler
    @command(C.NONE)
    def cb_pic(self, _, update):
        if not update.callback_query.message:
            self.logger.info('cb_pic no message')
        query = remove_control_chars(update.callback_query.message.caption)
        self.state.run_async(self._search, update, query)

    @update_handler
    @command(C.REPLY_TEXT_PAGINATED)
    def cmd_piclog(self, *_):
        return self.state.list_search_requests

    @update_handler
    @command(C.REPLY_TEXT_PAGINATED)
    def cb_pic_log(self, *_):
        return self.state.list_search_requests

    @update_handler
    @command(C.REPLY_TEXT_PAGINATED)
    def cmd_picstats(self, *_):
        return self.state.get_search_stats

    @update_handler
    @command(C.REPLY_TEXT_PAGINATED)
    def cb_pic_stats(self, *_):
        return self.state.get_search_stats

    @update_handler
    @command(C.REPLY_TEXT)
    def cmd_image(self, _, update):
        msg = update.message
        if msg.photo:
            pass
        elif msg.reply_to_message and msg.reply_to_message.photo:
            msg = msg.reply_to_message
        else:
            update.message.reply_text('no input image')
            return
        deferred = Promise.defer()
        download_file(msg, self.state.file_dir, deferred)
        return partial(self.state.on_photo, deferred)

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
        msg = get_command_args(update.message, help='usage: /echo <text>')
        bot.send_message(chat_id=update.message.chat_id, text=msg)

    @update_handler
    @command(C.NONE)
    def cmd_roll(self, _, update):
        msg = get_command_args(update.message, help='usage: /roll <dice>')
        roll = int(dice.roll(msg))
        update.message.reply_text(
            '<i>%s</i> → <b>%s</b>' % (msg, roll),
            quote=True,
            parse_mode=ParseMode.HTML
        )

    @update_handler
    @command(C.NONE)
    def cmd_format(self, _, update):
        msg = get_command_args(update.message, help='usage: /format <text>')
        msg = self.state.formatter.format(msg)
        update.message.reply_text(msg, parse_mode=ParseMode.HTML)

    @update_handler
    @command(C.NONE)
    def cmd_eval(self, _, update):
        msg = get_command_args(update.message, help='usage: /eval <expression>')
        msg = safe_eval(msg)
        msg = re.sub(r'\.?0+$', '', '%.04f' % msg)
        update.message.reply_text(msg, quote=True)

    @update_handler
    @command(C.NONE)
    def cmd_b64(self, _, update):
        msg = get_command_args(update.message, help='usage: /b64 <text>')
        msg = b64encode(msg.encode('utf-8')).decode('ascii')
        update.message.reply_text(msg, quote=True)

    @update_handler
    @command(C.NONE)
    def cmd_b64d(self, bot, update):
        msg = get_command_args(update.message, help='usage: /b64d <base64>')
        msg = b64decode(msg.encode('utf-8'), validate=True).decode('utf-8')
        bot.send_message(chat_id=update.message.chat_id, text=msg)

    @update_handler
    @command(C.NONE, P.ADMIN)
    def cmd_getuser(self, _, update):
        msg = update.message
        num = get_command_args(update.message, help='usage: /getuser <number>')
        if not is_phone_number(num):
            raise CommandError('invalid phone number')

        res = self._get_user_link(msg, num)
        if res is None:
            res = 'not found: ' + num
        msg.reply_text(res, parse_mode=ParseMode.MARKDOWN)

    @update_handler
    @command(C.REPLY_TEXT_PAGINATED)
    def cmd_getusers(self, _, update):
        return self.state.list_users

    @update_handler
    @command(C.REPLY_TEXT_PAGINATED)
    def cb_users(self, _, update):
        return self.state.list_users

    @update_handler
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

    @update_handler
    @command(C.REPLY_TEXT_PAGINATED)
    def cmd_getstickers(self, *_):
        return self.state.list_sticker_sets

    @update_handler
    @command(C.REPLY_TEXT_PAGINATED)
    def cb_sticker_sets(self, *_):
        return self.state.list_sticker_sets

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
    def cmd_setreplylength(self, *_):
        return self.state.set_reply_length

    @update_handler
    @command(C.REPLY_TEXT)
    def cmd_unsettrigger(self, *_):
        return self.state.remove_trigger
