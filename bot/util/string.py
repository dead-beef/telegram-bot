import re
import os
import unicodedata
from itertools import chain
from html.parser import HTMLParser

from .misc import re_list_compile


RE_SANITIZE_MSG = re_list_compile([
    (r'<LF>', '[LF]'),
    (r'\n+', ' <LF> '),
    (r'\s+', ' ')
])

RE_SANITIZE = RE_SANITIZE_MSG + re_list_compile([
    (r'[][|]', '.')
])

RE_COMMAND = re.compile(r'^/[^\s]+\s*')
RE_COMMAND_USERNAME = re.compile(r'^/[^@\s]+@([^\s]+)\s*')

RE_PHONE_NUMBER = re.compile(r'^\+[0-9]+$')


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


def srange(x, y, maxlen=None):
    if len(x) != len(y):
        raise ValueError('srange string length is not equal')
    if x > y:
        x, y = y, x
    elif x == y:
        yield x
        return
    prefix = os.path.commonprefix((x, y))
    suffix = len(x) - len(prefix)
    x = x[-suffix:]
    y = y[-suffix:]
    if not (x.isdigit() and y.isdigit()):
        raise ValueError('invalid range: %r - %r' % (x, y))
    x = int(x, 10)
    y = int(y, 10) + 1
    if maxlen is not None and y - x > maxlen:
        raise ValueError('invalid range length: %d > %d' % (y - x, maxlen))
    for i in range(x, y):
        yield '%s%0*d' % (prefix, suffix, i)

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

def is_phone_number(string):
    return RE_PHONE_NUMBER.match(string)

def trunc(string, max_length=1000):
    if len(string) > max_length:
        return '... ' + string[4 - max_length:]
    return string

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
