import re
import enum
import logging
import subprocess
import unicodedata
from functools import wraps
from itertools import chain
from html.parser import HTMLParser

import dice
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .error import BotError, CommandError
from .promise import Promise, PromiseType as PT


def re_list_compile(re_list):
    return [(re.compile(expr), repl) for expr, repl in re_list]


LOGGER = logging.getLogger(__name__)

RE_COMMAND = re.compile(r'^/[^\s]+\s*')
RE_COMMAND_USERNAME = re.compile(r'^/[^@\s]+@([^\s]+)\s*')

RE_PHONE_NUMBER = re.compile(r'^\+[0-9]+$')

RE_SANITIZE_MSG = re_list_compile([
    (r'<LF>', '[LF]'),
    (r'\n+', ' <LF> '),
    (r'\s+', ' ')
])

RE_SANITIZE = RE_SANITIZE_MSG + re_list_compile([
    (r'[][|]', '.')
])


FILE_TYPES = ['video', 'audio', 'document', 'voice', 'photo']


class CommandType(enum.IntEnum):
    NONE = 0
    REPLY_TEXT = 1
    REPLY_STICKER = 2
    GET_OPTIONS = 3
    SET_OPTION = 4


class HTMLFlattenParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.result = ''
        self.tags = []
        self.current_tag = None
        self.current_tag_start = None

    def handle_starttag(self, tag, attrs):
        tag_start = self.get_starttag_text()
        if self.current_tag is not None:
            self.tags.append((self.current_tag, self.current_tag_start))
            self.result += '</%s>' % self.current_tag
        self.current_tag, self.current_tag_start = tag, tag_start
        self.result += tag_start

    def handle_endtag(self, tag):
        if self.current_tag is None:
            return
        self.result += '</%s>' % self.current_tag
        self.current_tag = None
        if self.tags:
            self.current_tag, self.current_tag_start = self.tags.pop()
            self.result += self.current_tag_start

    def handle_data(self, data):
        self.result += data

    def handle_entityref(self, name):
        self.result += '&%s;' % name

    def handle_charref(self, name):
        self.result += '&%s;' % name

    def close(self):
        super().close()
        self.tags = []
        if self.current_tag is not None:
            self.result += '</%s>' % self.current_tag
            self.current_tag = None


def chunks(list_, size):
    for i in range(0, len(list_), size):
        yield list_[i:i + size]

def intersperse(*seq):
    return chain.from_iterable(zip(*seq))

def _intersperse_printable(string, ins, after=True):
    for x in string:
        cat = unicodedata.category(x)
        insert = x.isprintable() and (cat[0] not in 'MC' or cat == 'Cn')
        if insert and not after:
            yield ins
        yield x
        if insert and after:
            yield ins

def intersperse_printable(string, ins, after=True):
    return ''.join(_intersperse_printable(string, ins, after))

def flatten_html(data):
    parser = HTMLFlattenParser()
    parser.feed(data)
    parser.close()
    return parser.result


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


def is_phone_number(string):
    return RE_PHONE_NUMBER.match(string)

def remove_control_chars(string):
    return ''.join(
        char for char, cat in ((c, unicodedata.category(c)) for c in string)
        if cat[0] != 'C' or cat == 'Cn'
    )

def strip_command(string):
    return RE_COMMAND.sub('', string).strip()

def get_command_args(msg, nargs=1, help='missing command argument'):
    if nargs != 1:
        raise NotImplementedError('get_command_args nargs != 1')
    msg = strip_command(msg)
    if not msg:
        raise CommandError(help)
    return msg

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

def get_message_filename(message):
    return '%s_%s_%s' % (
        message.chat.id,
        int(message.date.timestamp()),
        message.message_id
    )

def get_message_text(message):
    return message.text or message.caption

def get_file(message):
    for type_ in FILE_TYPES:
        data = getattr(message, type_)
        if data:
            if type_ == 'photo':
                data = data[-1]
            return type_, data.file_id
    raise ValueError('%r: file not found', message)


def reply_text(update, msg, quote=False):
    if not msg:
        return

    if isinstance(msg, tuple) and len(msg) == 2:
        msg, quote = msg

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

    update.message.reply_text(msg, quote=quote)


def reply_sticker(update, msg, quote=False):
    if not msg:
        return
    if isinstance(msg, tuple) and len(msg) == 2:
        msg, quote = msg
    update.message.reply_sticker(sticker=msg, quote=quote)


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
                return

            try:
                res = method(self, bot, update)
            except (BotError, dice.DiceBaseException) as ex:
                update.message.reply_text(str(ex), quote=True)
                return
            except Exception as ex:
                update.message.reply_text(repr(ex), quote=True)
                raise

            if type_ == CommandType.NONE:
                return res
            elif type_ == CommandType.REPLY_TEXT:
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
