import re
import enum
import logging
import unicodedata
from functools import wraps

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .error import BotError
from .promise import Promise, PromiseType as PT


def re_list_compile(re_list):
    return [(re.compile(expr), repl) for expr, repl in re_list]


RE_COMMAND = re.compile(r'^/[^\s]+\s*')
RE_COMMAND_USERNAME = re.compile(r'^/[^@\s]+@([^\s]+)\s*')

RE_SANITIZE_MSG = re_list_compile([
    (r'<LF>', '[LF]'),
    (r'\n+', ' <LF> '),
    (r'\s+', ' ')
])

RE_SANITIZE = RE_SANITIZE_MSG + re_list_compile([
    (r'[][|]', '.')
])


class CommandType(enum.IntEnum):
    NONE = 0
    REPLY_TEXT = 1
    REPLY_STICKER = 2
    GET_OPTIONS = 3
    SET_OPTION = 4


def chunks(list_, size):
    for i in range(0, len(list_), size):
        yield list_[i:i + size]


def configure_logger(name,
                     log_file=None,
                     log_format=None,
                     log_level=logging.INFO):
    if isinstance(log_file, str):
        handler = logging.FileHandler(log_file, 'a')
    else:
        handler = logging.StreamHandler(log_file)

    formatter = logging.Formatter(log_format)
    logger = logging.getLogger(name)

    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(log_level)

    return logger


def remove_control_chars(string):
    return ''.join(
        char for char, cat in ((c, unicodedata.category(c)) for c in string)
        if cat[0] != 'C' or cat == 'Cn'
    )

def strip_command(string):
    return RE_COMMAND.sub('', string).strip()

def match_command_user(cmd, username):
    match = RE_COMMAND_USERNAME.match(cmd)
    if match is None:
        return True
    return match.group(1) == username

def sanitize_log(string, is_message=False):
    replace = RE_SANITIZE_MSG if is_message else RE_SANITIZE
    for expr, repl in replace:
        string = expr.sub(repl, string)
    string = remove_control_chars(string).strip()
    if not string:
        string = '<empty>'
    return string

def get_chat_title(chat):
    if chat.title is not None:
        return chat.title
    return '@%s %s %s' % (
        str(chat.username),
        str(chat.first_name),
        str(chat.last_name)
    )

def get_message_text(message):
    return message.text or message.caption


def reply_text(update, msg, quote=False):
    if not msg:
        return

    if isinstance(msg, tuple) and len(msg) == 2:
        msg, quote = msg

    if isinstance(msg, Exception):
        quote = True
        if isinstance(msg, BotError):
            msg = str(msg)
        else:
            msg = repr(msg)

    update.message.reply_text(msg, quote=quote)


def reply_sticker(update, msg, quote=False):
    if not msg:
        return
    if isinstance(msg, tuple) and len(msg) == 2:
        msg, quote = msg
    update.message.reply_sticker(sticker=msg, quote=quote)


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
        if self.stopped.is_set():
            self.logger.info('not handling updates: stopped')
            return
        try:
            method(self, bot, update)
        except Exception as ex:
            self.logger.error(ex)
            raise
    return ret


def command(type_):
    def decorator(method):
        @wraps(method)
        def ret(self, bot, update):
            self.logger.info('command %s', method.__name__)

            if(update.message
               and update.message.text
               and not match_command_user(update.message.text,
                                          self.state.username)):
                self.logger.info('!match_command_user %s' % update.message.text)
                return None

            if type_ == CommandType.NONE:
                return method(self, bot, update)

            if type_ == CommandType.REPLY_TEXT:
                on_resolve = lambda msg: reply_text(update, msg, True)
                on_reject = on_resolve
            elif type_ == CommandType.REPLY_STICKER:
                on_resolve = lambda msg: reply_sticker(update, msg, True)
                on_reject = lambda msg: reply_text(update, msg, True)
            elif type_ == CommandType.GET_OPTIONS:
                on_resolve = lambda res: reply_keyboard(update, res)
                on_reject = lambda msg: reply_text(update, msg, True)
            elif type_ == CommandType.SET_OPTION:
                on_resolve = lambda msg: reply_callback_query(update, msg)
                on_reject = on_resolve
            else:
                raise ValueError('invalid command type: %s' % type_)

            res = method(self, bot, update)
            if res is None:
                self.logger.info('%s: no command', method.__name__)
                return
            if isinstance(res, Promise):
                promise = res
            else:
                promise = Promise.wrap(res, update, ptype=PT.MANUAL)
            self.queue.put(promise)
            promise.then(on_resolve, on_reject).wait()

        return ret
    return decorator
