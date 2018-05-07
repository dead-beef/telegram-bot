import re
from unittest.mock import Mock
import pytest

from bot.util import (
    re_list_compile,
    remove_control_chars,
    strip_command,
    match_command_user,
    sanitize_log,
    get_chat_title
)


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
