import re
import os
import logging
import subprocess

from uuid import uuid4
from functools import partial

from telegram import (
    ChatAction,
    TelegramError,
    ParseMode,
    InlineQueryResultArticle,
    InputTextMessageContent
)
from telegram.ext import (
    MessageHandler,
    CallbackQueryHandler,
    Filters
)

from bot.promise import Promise, PromiseType as PT
from bot.util import (
    trunc,
    command,
    update_handler,
    reply_photo,
    reply_file,
    CommandType as C,
    Permission as P
)


class BotCommandBase:
    def __init__(self, bot):
        self.help = 'commands:\n'
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

    def _run_script(self, update, name, args,
                    download=None, no_output='<no output>',
                    return_image=False, return_file=None, timeout=None):
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
            ext = 'jpg' if return_image else return_file

            if ext is not None:
                tmp = os.path.join(self.state.tmp_dir, '%s_%s.%s' % (
                    update.effective_chat.id,
                    update.message.message_id,
                    ext
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

            if tmp is not None and os.path.exists(tmp):
                if return_image:
                    reply_photo(update, tmp, quote=True)
                else:
                    reply_file(update, tmp, quote=True)
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
            try:
                handler(bot, update)
            except Exception as ex:
                self.logger.error(ex)

    @update_handler
    def _callback_query(self, bot, update):
        msg = update.callback_query.message
        cmd = None
        has_cmd = False

        permission = self.state.db.get_user_data(
            update.callback_query.from_user,
            'permission'
        )

        if permission <= P.BANNED:
            return

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
    @command(C.REPLY_TEXT)
    def callback_query(self, bot, update):
        if update.callback_query is None:
            return None
        return partial(self._callback_query, bot)

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
