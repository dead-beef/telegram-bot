import pytest

from bot.formatter import Formatter, Token as T

@pytest.fixture
def default_tags():
    return {
        'b': {'html': 'b'},
        'i': {'html': 'i'},
        'a': {'html_attr': {
            'tag': 'a',
            'attr': 'href',
            'example_attr': 'http://example.com'
        }},
        'tr': {'translate': {'a': 'b', 'b': 'a'}},
        'xy': {'start': 'x', 'end': 'y'},
        's': {'intersperse_after': 'z'}
    }

@pytest.fixture
def default_replace():
    return {
        '0': '123',
        'abc': 'xyz'
    }

@pytest.fixture
def default_formatter(default_tags, default_replace):
    return Formatter(default_tags, default_replace)


@pytest.mark.parametrize('test,res', [
    ('', []),
    ('abc', [(T.STRING, 'abc')]),
    ('ab [b]cde[/b]', [(T.STRING, 'ab '), (T.TAG_START, ('b', '')),
                       (T.STRING, 'cde'), (T.TAG_END, 'b')]),
    ('ab [b]cde[/b]fg', [(T.STRING, 'ab '), (T.TAG_START, ('b', '')),
                         (T.STRING, 'cde'), (T.TAG_END, 'b'),
                         (T.STRING, 'fg')]),
    ('ab[b]cd[i]e[/b]fg[/i]', [(T.STRING, 'ab'),
                               (T.TAG_START, ('b', '')), (T.STRING, 'cd'),
                               (T.TAG_START, ('i', '')), (T.STRING, 'e'),
                               (T.TAG_END, 'b'), (T.STRING, 'fg'),
                               (T.TAG_END, 'i')]),
    ('[b]c[//b][xx][[]]e[/b]', [(T.TAG_START, ('b', '')),
                                (T.STRING, 'c[//b][xx]'),
                                (T.STRING, '[[]]e'),
                                (T.TAG_END, 'b')]),
    (
        '[a http://example.com][s]te[/s]s[/a]t',
        [(T.TAG_START, ('a', 'http://example.com')),
         (T.TAG_START, ('s', '')), (T.STRING, 'te'), (T.TAG_END, 's'),
         (T.STRING, 's'), (T.TAG_END, 'a'), (T.STRING, 't')
        ]
    )
])
def test_formatter_scan(test, res, default_formatter):
    assert list(default_formatter.scan(test)) == res


@pytest.mark.parametrize('test,res', [
    ([], []),
    ([(T.STRING, 'abc abcd dabc, abc')], [(T.STRING, 'xyz abcd dabc, xyz')]),
    (
        [(T.STRING, 'ab&'), (T.TAG_START, ('b', '')),
         (T.STRING, '<e>'), (T.TAG_END, 'b'),
         (T.TAG_START, ('tr', '')), (T.STRING, 'abc'),
         (T.STRING, 'abab'), (T.TAG_END, 'tr')],
        [(T.STRING, 'ab&amp;'), (T.HTML, '<b>'),
         (T.STRING, '&lt;e&gt;'), (T.HTML, '</b>'),
         (T.STRING, 'xyz'), (T.STRING, 'baba')],
    ),
    (
        [(T.STRING, 'ab'), (T.TAG_START, ('b', '')), (T.STRING, 'cd'),
         (T.TAG_START, ('i', '')), (T.STRING, 'e'), (T.TAG_END, 'b'),
         (T.STRING, 'fg'), (T.TAG_END, 'i')],
        [(T.STRING, 'ab'), (T.HTML, '<b>'), (T.STRING, 'cd'),
         (T.HTML, '<i>'), (T.STRING, 'e'), (T.HTML, '</i>'),
         (T.HTML, '</b>'), (T.STRING, 'fg')]
    ),
    (
        [(T.TAG_START, ('a', 'http://example.com')), (T.STRING, 'a')],
        [(T.HTML, '<a href="http://example.com">'),
         (T.STRING, 'a'),
         (T.HTML, '</a>')]
    )
])
def test_formatter_parse(test, res, default_formatter):
    assert list(default_formatter.parse(iter(test))) == res


@pytest.mark.parametrize('test,res', [
    ('', ''),
    ('abc [s]ab\ncd[/s] dabc,abc', 'xyz azbz\nczdz dabc,abc'),
    ('ab [b]cde', 'ab <b>cde</b>'),
    ('a[xy]b&[b]<>e[/b]f[/xy]g', 'axb&amp;<b>&lt;&gt;e</b>fyg'),
    ('ab[b]cd[i]e[/b]fg[/i]', 'ab<b>cd</b><i>e</i><b></b>fg'),
    ('[b]c[//b][xx][[]]e[/b]', '<b>c[//b][xx][[]]e</b>'),
    ('[a http://example.com?x=0&y="1"]test',
     '<a href="http://example.com?x=0&amp;y=&quot;1&quot;">test</a>')
])
def test_formatter_format(test, res, default_formatter):
    assert default_formatter.format(test) == res
