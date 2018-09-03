import re
from unittest.mock import Mock
import pytest

from bot.util import (
    srange,
    chunks,
    intersperse,
    intersperse_printable,
    flatten_html,
    re_list_compile,
    remove_control_chars,
    strip_command,
    match_command_user,
    sanitize_log,
    get_chat_title
)


@pytest.mark.parametrize('test,res', [
    ((range(4), 1), [[0], [1], [2], [3]]),
    ((range(4), 2), [[0, 1], [2, 3]]),
    ((range(4), 3), [[0, 1, 2], [3]]),
    ((range(4), 4), [[0, 1, 2, 3]])
])
def test_chunks(test, res):
    assert [list(chunk) for chunk in chunks(*test)] == res


@pytest.mark.parametrize('test,res', [
    (('', ''), ['']),
    (('1', '3'), ['1', '2', '3']),
    (('ab01', 'ab10'), ['ab01', 'ab02', 'ab03', 'ab04', 'ab05',
                        'ab06', 'ab07', 'ab08', 'ab09', 'ab10']),
    (('xx999', 'xx997', 3), ['xx997', 'xx998', 'xx999']),
    (('xyz', 'xyz'), ['xyz']),
    (('xyz', 'xyu'), None),
    (('xy00', 'xy-1'), None),
    (('0', '10'), None),
    (('01', '10', 9), None)
])
def test_srange(test, res):
    if res is None:
        with pytest.raises(ValueError):
            list(srange(*test))
    else:
        assert list(srange(*test)) == res

@pytest.mark.parametrize('test,res', [
    ((range(3),), [0, 1, 2]),
    (('abcd', range(3),), ['a', 0, 'b', 1, 'c', 2]),
    (('abcd', [0, 1], [2, 3, 4, 5]), ['a', 0, 2, 'b', 1, 3]),
])
def test_intersperse(test, res):
    assert list(intersperse(*test)) == res


@pytest.mark.parametrize('test,res', [
    (('abcd', ' ', True), 'a b c d '),
    (('abcd', '\n', False), '\na\nb\nc\nd'),
    (('a\nb \nc\u0338d', '_', True), 'a_\nb_ _\nc_\u0338d_')
])
def test_intersperse_printable(test, res):
    assert intersperse_printable(*test) == res


@pytest.mark.parametrize('test,res', [
    ('test', 'test'),
    ('t<b>e s</b>t', 't<b>e s</b>t'),
    ('t<b>e st', 't<b>e st</b>'),
    ('a b c<b>d e<i>f g<u> h i</u> <b>h</b> s</i>t',
     'a b c<b>d e</b><i>f g</i><u> h i</u><i> </i><b>h</b><i> s</i><b>t</b>'),
    ('a<b><i><u>b', 'a<b></b><i></i><u>b</u>')
])
def test_flatten_html(test, res):
    assert flatten_html(test) == res


@pytest.mark.parametrize('test', [
    [(r'.+', ''), (re.compile('.'), '/')]
])
def test_re_list_compile(test):
    res = re_list_compile(test)
    res = [(expr.pattern, repl) for expr, repl in res]
    test = [
        (expr if isinstance(expr, str) else expr.pattern, repl)
        for expr, repl in test
    ]
    assert res == test


@pytest.mark.parametrize('test,res', [
    (' aб\r\nb c d\u200b\u007f\U000f0000\udc00.,/?\U0001f923',
     ' aбb c d.,/?\U0001f923')
])
def test_remove_control_chars(test, res):
    assert remove_control_chars(test) == res


@pytest.mark.parametrize('test,res', [
    ('/cmd ', ''),
    ('/cmd  arg   arg2 arg3  ', 'arg   arg2 arg3'),
    ('/cmd@x0_bot arg', 'arg')
])
def test_strip_command(test, res):
    assert strip_command(test) == res


@pytest.mark.parametrize('test,res', [
    (('/cmd', 'user'), True),
    (('/cmd arg', 'user'), True),
    (('/cmd@user', 'user'), True),
    (('/cmd@user arg', 'user'), True),
    (('/cmd@user2', 'user'), False),
    (('/cmd@user2 arg', 'user'), False)
])
def test_match_command_user(test, res):
    assert match_command_user(*test) == res


@pytest.mark.parametrize('test,is_msg,res', [
    ('    ', False, '<empty>'),
    ('  \u200b \u007f  ', True, '<empty>'),
    ('te<LF>st\n\n te     st', True, 'te[LF]st <LF> te st'),
    ('a||[b]<LF>\n', False, 'a...b..LF. <LF>'),
    ('a||[b]<LF>\n', True, 'a||[b][LF] <LF>'),
    ('a\u200b\u007f\U000f0000\udc00.,/?\U0001f923', False, 'a.,/?\U0001f923')
])
def test_sanitize_log(test, is_msg, res):
    assert sanitize_log(test, is_msg) == res


@pytest.mark.parametrize('test,res', [
    (
        Mock(title='title', username='user', first_name=None, last_name=None),
        'title'
    ),
    (
        Mock(title=None, username='user', first_name=None, last_name=None),
        '@user None None'
    ),
    (
        Mock(title=None, username=None, first_name='first', last_name='last'),
        '@None first last'
    ),
])
def test_get_chat_title(test, res):
    assert get_chat_title(test) == res
