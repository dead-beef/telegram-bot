import os
import re
import logging
import subprocess
from time import sleep
from functools import wraps

import dice
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatAction,
    TelegramError
)

from bot.error import BotError, CommandError
from bot.promise import Promise, PromiseType as PT

from .enums import Permission, CommandType
from .string import match_command_user, strip_command
from .misc import chunks


LOGGER = logging.getLogger(__name__)

RE_COMMAND = re.compile(r'^/[^\s]+\s*')
RE_COMMAND_USERNAME = re.compile(r'^/[^@\s]+@([^\s]+)\s*')

RE_ANIMATION_URL = re.compile(r'^[^?&]*\.gif([?&].*)?$', re.I)

FILE_TYPES = ['video', 'audio', 'document', 'voice', 'photo']


def get_chat_title(chat):
    if chat.title is not None:
        return chat.title
    return '@%s %s %s' % (
        str(chat.username),
        str(chat.first_name),
        str(chat.last_name)
    )

def get_user_name(user, notification=True):
    if user.username:
        ret = user.username
        if notification:
            ret = '@' + ret
        return ret
    if user.first_name or user.last_name:
        return ' '.join(
            s for s in (user.first_name, user.last_name) if s
        )
    return str(user.id)

def get_message_filename(message):
    return '%s_%s_%s' % (
        message.chat.id,
        int(message.date.timestamp()),
        message.message_id
    )

def get_message_text(message):
    return message.text or message.caption or ''

def get_command_args(msg, nargs=1, help='missing command argument'):
    if nargs != 1:
        raise NotImplementedError('get_command_args nargs != 1')
    args = strip_command(get_message_text(msg))
    if not args:
        raise CommandError(help)
    return args

def get_file(message):
    for type_ in FILE_TYPES:
        data = getattr(message, type_)
        if data:
            if type_ == 'photo':
                data = data[-1]
            return type_, data.file_id
    raise ValueError('%r: file not found' % message)

def download_file(message, dirs, deferred=None, overwrite=False):
    try:
        ftype, fid = None, None
        ftype, fid = get_file(message)
        fdir = dirs[ftype]
        fname = os.path.join(fdir, get_message_filename(message))
        if os.path.exists(fname) and not overwrite:
            LOGGER.info('%s file exists: %s', ftype, fname)
        else:
            LOGGER.info('download %s -> %s', ftype, fname)
            message.bot.get_file(fid).download(fname)
            LOGGER.info('download complete: %s -> %s', ftype, fname)
    except BaseException as ex:
        LOGGER.error('download error: %r -> %r: %r', ftype, fname, ex)
        if deferred is not None:
            deferred.reject(ex)
        raise
    else:
        if deferred is not None:
            deferred.resolve(fname)

def reply_text(update, msg, quote=False, parse_mode=None):
    if not msg:
        return

    if isinstance(msg, tuple):
        if len(msg) == 2:
            msg, quote = msg
        elif len(msg) == 3:
            msg, quote, parse_mode = msg

    if isinstance(msg, Exception):
        quote = True
        if isinstance(msg, BotError):
            msg = str(msg)
        elif isinstance(msg, subprocess.CalledProcessError):
            LOGGER.error('%s\n\n%r', msg.output.decode('utf-8'), msg)
            msg = 'subprocess exited with status %d' % msg.returncode
        elif isinstance(msg, subprocess.TimeoutExpired):
            msg = 'subprocess timeout expired'
        else:
            msg = repr(msg)

    update.message.reply_text(msg, quote=quote, parse_mode=parse_mode)

def reply_text_paginated(update, msg, quote=False, parse_mode=None, disable_notification=False):
    page = 1
    pages = 1
    max_pages = 8

    if isinstance(msg, tuple):
        if len(msg) == 2:
            msg, pages = msg
        elif len(msg) == 3:
            msg, page, pages = msg
        elif len(msg) == 4:
            msg, page, pages, quote = msg
        elif len(msg) == 5:
            msg, page, pages, quote, parse_mode = msg

    if pages <= 1:
        return reply_text(update, msg, quote, parse_mode)

    if pages <= max_pages:
        buttons = ((str(i), i) for i in range(1, pages + 1))
    else:
        min_page = page - int(max_pages / 2)
        max_page = page + int(max_pages / 2)
        if min_page <= 0:
            max_page -= min_page - 1
            min_page = 1
        elif max_page > pages:
            min_page -= max_page - pages - 1
            max_page = pages + 1
        buttons = [
            ('1', 1) if i == min_page
            else (str(pages), pages) if i == max_page - 1
            else ('...' if (i == min_page + 1 and i != 2
                            or i == max_page - 2 and i != pages - 1)
                  else str(i), i)
            for i in range(min_page, max_page)
        ]

    keyboard = [
        InlineKeyboardButton(title, callback_data=value)
        for title, value in buttons
    ]
    keyboard = list(chunks(keyboard, 4))
    markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        update.callback_query.message.edit_text(
            msg,
            parse_mode=parse_mode,
            disable_notification=disable_notification,
            reply_markup=markup
        )
    else:
        update.message.reply_text(
            msg,
            quote=quote,
            parse_mode=parse_mode,
            disable_notification=disable_notification,
            reply_markup=markup
        )

def reply_sticker(update, msg, quote=False):
    if not msg:
        return
    if isinstance(msg, tuple) and len(msg) == 2:
        msg, quote = msg
    update.message.reply_sticker(sticker=msg, quote=quote)

def reply_sticker_set(update, stickers, quote=False):
    for sticker in stickers:
        try:
            update.message.bot.send_chat_action(
                update.message.chat_id,
                ChatAction.TYPING
            )
        except TelegramError:
            pass
        sleep(0.5)
        update.message.reply_sticker(sticker=sticker[0], quote=quote)

def reply_photo(update, img, quote=False):
    if isinstance(img, str):
        with open(img, 'rb') as fp:
            update.message.reply_photo(fp, quote=quote)
    else:
        update.message.reply_photo(img, quote=quote)


def reply_keyboard(update, msg, options=None):
    if isinstance(msg, tuple) and len(msg) == 2:
        msg, options = msg
    if not options:
        reply_text(update, msg, quote=True)
        return
    keyboard = [
        InlineKeyboardButton(str(value), callback_data=value)
        for value in options
    ]
    keyboard = list(chunks(keyboard, 2))
    markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(msg, reply_markup=markup)


def reply_callback_query(update, msg):
    if not msg:
        return
    if isinstance(msg, Exception):
        if isinstance(msg, BotError):
            msg = str(msg)
        else:
            msg = repr(msg)
    message = update.callback_query.message
    message.edit_text(msg)

def send_image(bot, chat_id, url, *args, **kwargs):
    LOGGER.debug('send_image %r %r', url, RE_ANIMATION_URL.match(url))
    if RE_ANIMATION_URL.match(url):
        LOGGER.debug('send_animation')
        bot.send_animation(chat_id, url, *args, **kwargs)
    else:
        LOGGER.debug('send_photo')
        bot.send_photo(chat_id, url, *args, **kwargs)


def update_handler(method):
    @wraps(method)
    def ret(self, bot, update):
        self.logger.debug(
            'update: %s: chat=%s user=%s message=%s',
            method.__name__,
            update.effective_chat,
            update.effective_user,
            update.effective_message
        )
        if hasattr(self, 'log_update'):
            self.log_update(update)
        if self.stopped.is_set():
            self.logger.info('not handling updates: stopped')
            return
        try:
            method(self, bot, update)
        except Exception as ex:
            self.logger.error(ex)
            raise
    return ret


def check_permission(bot, user, min_value=Permission.USER):
    get_permission = Promise.wrap(
        bot.state.db.get_user_data,
        user,
        'permission',
        ptype=PT.MANUAL
    )
    bot.queue.put(get_permission)
    get_permission.wait()
    value = get_permission.value
    if not isinstance(value, int):
        bot.logger.error('check_permission: %r', value)
        return False, True
    return value >= min_value, value > Permission.IGNORED


def command(type_, permission=Permission.USER):
    def decorator(method):
        @wraps(method)
        def ret(self, bot, update):
            self.logger.info('command %s', method.__name__)

            if update.message is not None:
                if(update.message.text
                   and not match_command_user(update.message.text,
                                              self.state.username)):
                    self.logger.info('!match_command_user %s'
                                     % update.message.text)
                    return

                perm, reply = check_permission(
                    self, update.message.from_user, permission
                )
                if not perm:
                    if reply:
                        self.logger.warning(
                            'permission denied: %s', update.message
                        )
                        update.message.reply_text(
                            'permission denied',
                            quote=True
                        )
                    return

            try:
                res = method(self, bot, update)
            except (BotError, dice.DiceBaseException) as ex:
                update.message.reply_text(str(ex), quote=True)
                return
            except Exception as ex:
                update.message.reply_text(repr(ex), quote=True)
                raise

            on_resolve = lambda msg: reply_text(update, msg, True)
            on_reject = on_resolve

            if type_ == CommandType.NONE:
                return res
            elif type_ == CommandType.REPLY_TEXT:
                pass
            elif type_ == CommandType.REPLY_STICKER:
                on_resolve = lambda msg: reply_sticker(update, msg, True)
            elif type_ == CommandType.GET_OPTIONS:
                on_resolve = lambda res: reply_keyboard(update, res)
            elif type_ == CommandType.SET_OPTION:
                on_resolve = lambda msg: reply_callback_query(update, msg)
                on_reject = on_resolve
            elif type_ == CommandType.REPLY_TEXT_PAGINATED:
                on_resolve = lambda msg: reply_text_paginated(update, msg, True)
            else:
                raise ValueError('invalid command type: %s' % type_)

            if res is None:
                self.logger.info('%s: no command', method.__name__)
                return
            if isinstance(res, Promise):
                promise = res
            elif not callable(res):
                on_resolve(res)
                return
            else:
                promise = Promise.wrap(res, update, ptype=PT.MANUAL)
            self.queue.put(promise)
            promise.then(on_resolve, on_reject).wait()

        return ret
    return decorator
