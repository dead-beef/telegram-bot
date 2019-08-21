import re
import os
import random
import logging
import subprocess

from uuid import uuid4
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
from telegram.error import BadRequest, Unauthorized

from .safe_eval import safe_eval
from .error import CommandError, SearchError
from .promise import Promise, PromiseType as PT
from .util import (
    trunc,
    remove_control_chars,
    get_command_args,
    get_user_name,
    get_message_text,
    strip_command,
    send_image,
    command,
    update_handler,
    is_phone_number,
    reply_sticker_set,
    reply_photo,
    CommandType as C,
    Permission as P
)


class BotCommands:
    HELP = (
        '/help - bot help\n'
        '/helptags - list formatter tags\n'
        '/helpemotes - list formatter emotes\n'
        '\n'
        '/alias - list aliases\n'
        '/aadd <regexp>=<string> - add alias\n'
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
        '\n'
        '/b64 <text> - encode base64\n'
        '/b64d <base64> - decode base64\n'
        '/echo <text> - print text\n'
        '/format <text> - format text\n'
        '/eval <expression> - evaluate expression\n'
        '/roll <dice> [message] - roll dice\n'
        '/pic <query> - image search\n'
        '/piclog - show image search log\n'
        '/picstats - show image search stats\n'
        '/start - generate text\n'
        '/image - generate image\n'
        '/ocr [language[+language...]] - ocr\n'
        '/sticker - send random sticker\n'
        '\n'
        '/getstickers - list sticker sets\n'
        '/getuser <+number> - get user by number\n'
        '/getusers - list users\n'
        '/stickerset <id> - send sticker set\n'
        '/q <query> - sql query\n'
        '/qr <query> - sql query (read only)\n'
        '/qplot <query> - sql query plot (read only)\n'
    )

    RE_DICE = re.compile(r'^\s*([0-9d][-+0-9duwtfrF%hml^ov ]*)')
    RE_ALIAS = re.compile(r'^\s*(\S.*)=\s*(\S.*)$')

    def __init__(self, bot):
        self.logger = logging.getLogger('bot.commands')
        self.state = bot.state
        self.formatter_tags = self.state.formatter.list_tags()
        self.formatter_emotes = self.state.formatter.list_emotes()
        self.queue = bot.queue
        self.stopped = bot.stopped
        dispatcher = bot.primary.dispatcher
        dispatcher.add_handler(MessageHandler(
            Filters.status_update,
            self.status_update
        ))
        for updater in bot.updaters:
            dispatcher = updater.dispatcher
            dispatcher.add_handler(CallbackQueryHandler(
                self.callback_query
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

    def _search(self, update, query, reset=False):
        if update.callback_query:
            user = update.callback_query.from_user
            reply_to = None
        else:
            user = update.message.from_user
            reply_to = update.message.message_id

        learn = Promise.wrap(
            self.state.db.learn_search_query,
            query, user, reset,
            ptype=PT.MANUAL
        )
        self.state.bot.queue.put(learn)
        learn.wait()
        offset = learn.value

        chat = update.effective_chat
        chat_id = chat.id

        primary_bot = self.state.bot.primary.bot
        if chat.type == chat.PRIVATE:
            bot = primary_bot
        else:
            bot = self.state.bot.updaters[-1].bot

        try:
            bot.send_chat_action(chat_id, ChatAction.UPLOAD_PHOTO)
        except (Unauthorized, BadRequest) as ex:
            self.logger.warning('send_chat_action: %r', ex)
            try:
                primary_bot.send_message(
                    chat_id,
                    'add secondary bot to group',
                    quote=True,
                    reply_to_message_id=reply_to
                )
            except TelegramError as ex:
                self.logger.warning('send error message: %r', ex)
            return
        except TelegramError as ex:
            self.logger.error('send_chat_action: %r', ex)

        try:
            res, is_last = self.state.search(query, offset)
        except SearchError as ex:
            primary_bot.send_message(
                chat_id,
                str(ex),
                quote=True,
                reply_to_message_id=reply_to
            )
        except Exception as ex:
            primary_bot.send_message(
                chat_id,
                repr(ex),
                quote=True,
                reply_to_message_id=reply_to
            )
            return
        else:
            keyboard = [
                InlineKeyboardButton(
                    '\U0001f517 %d' % (offset + 1),
                    url=res.url
                )
            ]
            if offset >= 1:
                keyboard.append(
                    InlineKeyboardButton('reset', callback_data='picreset')
                )
            if not is_last:
                keyboard.append(
                    InlineKeyboardButton('next', callback_data='pic')
                )
            keyboard = InlineKeyboardMarkup([keyboard])
            for url in (res.image, res.thumbnail, None):
                try:
                    self.logger.info('%r %r', query, url)
                    if url is None:
                        bot.send_message(
                            chat_id,
                            '(bad request)\n%s\n%s\n\n%s' % (
                                res.image, res.url, query
                            )
                        )
                    else:
                        send_image(
                            bot, chat_id, url,
                            caption=query,
                            reply_markup=keyboard
                        )
                    return
                except TelegramError as ex:
                    self.logger.info('image post failed: %r: %r', res, ex)

    def _run_script(self, update, name, args,
                    download=None, no_output='<no output>',
                    return_image=False, timeout=None):
        try:
            update.message.bot.send_chat_action(
                update.effective_chat.id,
                ChatAction.UPLOAD_PHOTO if return_image
                else ChatAction.TYPING
            )
        except TelegramError:
            pass
        try:
            tmp = None

            if return_image:
                tmp = os.path.join(self.state.tmp_dir, '%s_%s_plot.jpg' % (
                    update.effective_chat.id,
                    update.message.message_id
                ))
                args = [tmp if arg == '{{TMP}}' else arg for arg in args]

            if download is not None:
                download.wait()
                args.insert(0, download.value)

            args.insert(0, os.path.join(self.state.root, 'scripts', name))

            output = subprocess.check_output(
                args,
                stderr=subprocess.STDOUT,
                timeout=timeout or self.state.process_timeout
            ).decode('utf-8').strip() or no_output

            if return_image and os.path.exists(tmp):
                reply_photo(update, tmp, quote=True)
            else:
                update.message.reply_text(trunc(output), quote=True)
        except Exception as ex:
            update.message.reply_text(repr(ex), quote=True)
        finally:
            if tmp is not None:
                try:
                    os.remove(tmp)
                except FileNotFoundError:
                    pass

    def on_command(self, bot, update):
        msg = update.message.text
        match = self.state.RE_COMMAND.match(msg)
        if match is None:
            self.logger.debug('!match command %s', msg)
            return
        handler = 'cmd_' + match.group(1).lower()

        try:
            handler = getattr(self, handler)
        except AttributeError:
            if update.message.chat.type == update.message.chat.PRIVATE:
                update.message.reply_text(
                    'unknown command "%s"' % msg,
                    quote=True
                )
        else:
            handler(bot, update)

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
        return self.state.on_status_update(type_, update)

    @command(C.REPLY_TEXT)
    def cmd_start(self, _, update):
        return self.state.random_text(update)

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

    @command(C.NONE)
    def cmd_pic(self, _, update):
        query = get_command_args(update.message, help='usage: /pic <query>')
        query = remove_control_chars(query).replace('\n', ' ')
        self.state.run_async(self._search, update, query)

    @command(C.NONE)
    def cb_pic(self, _, update):
        if not update.callback_query.message:
            self.logger.info('cb_pic no message')
        query = remove_control_chars(update.callback_query.message.caption)
        self.state.run_async(self._search, update, query)

    @command(C.NONE)
    def cb_picreset(self, _, update):
        if not update.callback_query.message:
            self.logger.info('cb_picreset no message')
        query = remove_control_chars(update.callback_query.message.caption)
        self.state.run_async(self._search, update, query, True)

    @command(C.REPLY_TEXT_PAGINATED)
    def cmd_piclog(self, _, update):
        return self.state.list_search_requests(update)

    @command(C.REPLY_TEXT_PAGINATED)
    def cb_pic_log(self, *_):
        return self.state.list_search_requests

    @command(C.REPLY_TEXT_PAGINATED)
    def cmd_picstats(self, _, update):
        return self.state.get_search_stats(update)

    @command(C.REPLY_TEXT_PAGINATED)
    def cb_pic_stats(self, *_):
        return self.state.get_search_stats

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
        self.state.bot.download_file(msg, self.state.file_dir, deferred)
        return self.state.on_photo(deferred, update)

    @command(C.NONE)
    def cmd_ocr(self, _, update):
        msg = update.message
        args = strip_command(msg.text)

        if args and not re.match(r'^[a-z]{3}(\+[a-z]{3})*$', args):
            update.message.reply_text('invalid language %r' % args)
            return

        if msg.photo:
            pass
        elif msg.reply_to_message and msg.reply_to_message.photo:
            msg = msg.reply_to_message
        else:
            update.message.reply_text('no input image')
            return

        deferred = Promise.defer()
        self.state.bot.download_file(msg, self.state.file_dir, deferred)
        self.state.run_async(self._run_script, update,
                             'ocr', [args], deferred.promise, 'no text found')

    @command(C.REPLY_STICKER)
    def cmd_sticker(self, *_):
        return self.state.db.random_sticker(), True

    @command(C.REPLY_TEXT)
    def cmd_help(self, *_):
        return self.HELP

    @command(C.REPLY_TEXT)
    def cmd_helptags(self, *_):
        return self.formatter_tags, True, ParseMode.HTML

    @command(C.REPLY_TEXT)
    def cmd_helpemotes(self, *_):
        return self.formatter_emotes

    @command(C.NONE)
    def cmd_echo(self, bot, update):
        msg = get_command_args(update.message, help='usage: /echo <text>')
        bot.send_message(chat_id=update.message.chat_id, text=msg)

    @command(C.REPLY_TEXT)
    def cmd_roll(self, _, update):
        help_ = ('usage:\n'
                 '/roll <dice> [message]\n'
                 '/roll <string> || <string> [|| <string>...]\n')
        msg = get_command_args(update.message, help=help_)
        match = self.RE_DICE.match(msg)
        if match is None:
            settings = self.state.get_chat_settings(update.message.chat)
            separator = settings['roll_separator']
            strings = [s for s in re.split(separator, msg, re.I) if s]
            if len(strings) < 2:
                return help_, True
            return random.choice(strings), True
        msg = match.group(1).strip()
        roll = int(dice.roll(msg))
        return (
            '<i>%s</i> → <b>%s</b>' % (msg, roll),
            True, ParseMode.HTML
        )

    @command(C.REPLY_TEXT)
    def cmd_format(self, _, update):
        msg = get_command_args(update.message, help='usage: /format <text>')
        msg = self.state.formatter.format(msg)
        return msg, True, ParseMode.HTML

    @command(C.REPLY_TEXT)
    def cmd_eval(self, _, update):
        msg = get_command_args(update.message, help='usage: /eval <expression>')
        msg = safe_eval(msg)
        msg = re.sub(r'\.?0+$', '', '%.04f' % msg)
        return msg, True

    @command(C.REPLY_TEXT)
    def cmd_b64(self, _, update):
        msg = get_command_args(update.message, help='usage: /b64 <text>')
        msg = b64encode(msg.encode('utf-8')).decode('ascii')
        return msg, True

    @command(C.NONE)
    def cmd_b64d(self, bot, update):
        msg = get_command_args(update.message, help='usage: /b64d <base64>')
        msg = b64decode(msg.encode('utf-8'), validate=True).decode('utf-8')
        bot.send_message(chat_id=update.message.chat_id, text=msg)

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
        return self.state.list_users

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
    def cb_sticker_sets(self, *_):
        return self.state.list_sticker_sets

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
