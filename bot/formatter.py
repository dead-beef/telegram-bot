import re
import html
import enum

from .util import intersperse_printable, flatten_html



class Token(enum.IntEnum):
    STRING = 0
    TAG_START = 1
    TAG_END = 2
    HTML = 3


class EndTag(Exception):
    def __init__(self, tag):
        super().__init__()
        self.tag = tag


class Tag:
    TYPES = [
        'html', 'html_attr', 'replace',
        'translate', 'translate_reverse',
        'intersperse_after', 'intersperse_before'
    ]

    def __init__(self,
                 start_string=None,
                 end_string=None,
                 transform=None,
                 example_attr=None):
        self.start_string = start_string
        self.end_string = end_string
        self.transform = transform or (lambda x: x)
        self.example_attr = example_attr

    def start(self, attr):
        if self.start_string is not None:
            yield (Token.HTML, self.start_string.format(attr))

    def end(self):
        if self.end_string is not None:
            yield (Token.HTML, self.end_string)

    @classmethod
    def html(cls, tag):
        return cls('<%s>' % tag, '</%s>' % tag)

    @classmethod
    def html_attr(cls, data):
        tag, attr = data['tag'], data['attr']
        ex = data.get('example_attr', None)
        return cls('<%s %s="{0}">' % (tag, attr),
                   '</%s>' % tag,
                   example_attr=ex)

    @classmethod
    def intersperse_after(cls, string):
        return cls(
            None, None,
            lambda inp: intersperse_printable(inp, string, True)
        )

    @classmethod
    def intersperse_before(cls, string):
        return cls(
            None, None,
            lambda inp: intersperse_printable(inp, string, False)
        )

    @classmethod
    def replace(cls, string):
        return cls(
            None, None,
            lambda inp: string * max(1, len(inp) // len(string))
        )

    @classmethod
    def translate(cls, table):
        table = dict((ord(key), value) for key, value in table.items())
        return cls(transform=lambda s: s.translate(table))

    @classmethod
    def translate_reverse(cls, table):
        table = dict((ord(key), value) for key, value in table.items())
        return cls(transform=lambda s: s[::-1].translate(table))

    @classmethod
    def load(cls, data):
        if isinstance(data, cls):
            return data
        for type_ in cls.TYPES:
            try:
                data = data[type_]
            except KeyError:
                continue
            return getattr(cls, type_)(data)
        return cls(data.get('start', None), data.get('end', None))


class Formatter:
    def __init__(self,
                 tags=None,
                 emotes=None,
                 tag_open_start='[',
                 tag_close_start='[/',
                 tag_end=']'):
        self.tags = {
            name: Tag.load(value)
            for name, value in (tags or {}).items()
        }
        self.tags[None] = Tag(transform=html.escape)

        self.tag_open_start = tag_open_start
        self.tag_close_start = tag_close_start
        self.tag_end = tag_end
        self.tag_expr = re.compile(r'(%s|%s)([a-z_]+)(\s+[^%s]+)?%s' % (
            re.escape(self.tag_open_start),
            re.escape(self.tag_close_start),
            re.escape(self.tag_end[0]),
            re.escape(self.tag_end)
        ))

        self.emotes = [
            (re.compile(r'(^|\s)%s($|\s)' % re.escape(expr)), r'\1%s\2' % repl)
            #if isinstance(expr, str) else (expr, repl)
            for expr, repl in (emotes.items()
                               if isinstance(emotes, dict)
                               else (emotes or []))
        ]

    def list_tags(self):
        tags = ''
        for tag in sorted(x for x in self.tags.keys() if x is not None):
            attr = self.tags[tag].example_attr
            attr = '' if attr is None else ' %s' % attr
            tag = '{1}{0}{4}{3}text{2}{0}{3}'.format(
                tag,
                self.tag_open_start,
                self.tag_close_start,
                self.tag_end,
                attr
            )
            tags += '%s → %s\n' % (html.escape(tag), self.format(tag))
        if not tags:
            tags = 'none'
        return tags

    def list_emotes(self):
        ret = ''
        for expr, repl in sorted(self.emotes, key=lambda x: x[0].pattern):
            pattern = expr.pattern
            ret += '%s → %s\n' % (pattern[6:-6], repl[2:-2])
        if not ret:
            ret = 'none'
        return ret

    def exec_emotes(self, string):
        for expr, repl in self.emotes:
            string = expr.sub(repl, string)
        return string

    def scan(self, string):
        prev = 0
        for match in self.tag_expr.finditer(string):
            start, end = match.span()
            tag = match.group(2)
            if tag in self.tags:
                if start > prev:
                    yield (Token.STRING, string[prev:start])
                if match.group(1) == self.tag_open_start:
                    attr = match.group(3)
                    attr = html.escape(attr.strip()) if attr is not None else ''
                    yield (Token.TAG_START, (tag, attr))
                else:
                    yield (Token.TAG_END, tag)
            else:
                yield (Token.STRING, string[prev:end])
            prev = end
        if prev < len(string):
            yield (Token.STRING, string[prev:])

    def parse(self, tokens, tag_name=None, tag_attr='', emotes=True):
        tag = self.tags[tag_name]
        yield from tag.start(tag_attr)
        try:
            for type_, value in tokens:
                if type_ == Token.TAG_END:
                    if tag_name is not None and value != tag_name:
                        raise EndTag(value)
                    break
                elif type_ == Token.TAG_START:
                    try:
                        for child in self.parse(tokens, value[0],
                                                value[1], emotes):
                            if child[0] == Token.HTML:
                                yield child
                            elif child[0] == Token.STRING:
                                yield (Token.STRING, tag.transform(child[1]))
                            else:
                                raise ValueError(child)
                    except EndTag as ex:
                        if ex.tag == tag_name:
                            break
                        elif tag_name is not None:
                            raise
                else:
                    if emotes:
                        value = self.exec_emotes(value)
                    yield (Token.STRING, tag.transform(value))
        finally:
            yield from tag.end()

    def format(self, string, emotes=True):
        return flatten_html(''.join(
            s for _, s in self.parse(self.scan(string), emotes=emotes)
        ))

    @classmethod
    def load(cls, data):
        if isinstance(data, cls):
            return data
        return cls(
            data.get('tags', None),
            data.get('emotes', None),
            data.get('tag_open_start', '['),
            data.get('tag_close_start', '[/'),
            data.get('tag_end', ']')
        )
