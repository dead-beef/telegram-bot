# pylint: disable=protected-access
from time import sleep
from unittest.mock import Mock
import pytest

from bot.promise import (
    Promise,
    PromiseState as S,
    PromiseType as T,
    PromiseTimeout,
    PromiseStateNotSet
)


def test_promise_resolve():
    p = Promise.resolve(0)
    assert p._state == S.RESOLVED
    assert p._value == 0
    assert p._timeout is None
    assert p._thread is None
    assert p._event.is_set()


def test_promise_reject():
    p = Promise.reject(1)
    assert p._state == S.REJECTED
    assert p._value == 1
    assert p._timeout is None
    assert p._thread is None
    assert p._event.is_set()


def test_promise_default():
    run = Mock(wraps=lambda resolve, reject: resolve(2))
    p = Promise(run)
    assert p._state == S.PENDING
    assert p._value is None
    assert p._timeout is None
    assert p._thread is None
    assert run.call_count == 0
    assert not p._event.is_set()

    assert p.wait()
    run.assert_called_once_with(p._resolve, p._reject)
    assert p._state == S.RESOLVED
    assert p._value == 2
    assert p._event.is_set()

    run.reset_mock()
    assert p.wait()
    assert run.call_count == 0


def test_promise_immediate():
    run = Mock(wraps=lambda resolve, reject: resolve(2))
    p = Promise(run, ptype=T.IMMEDIATE)
    run.assert_called_once_with(p._resolve, p._reject)
    assert p._state == S.RESOLVED
    assert p._value == 2
    assert p._event.is_set()
    assert p.wait()


def test_promise_manual():
    run = Mock(wraps=lambda resolve, reject: resolve(2))
    p = Promise(run, T.MANUAL)
    assert p._state == S.PENDING
    assert p._value is None
    assert p._timeout is None
    assert p._thread is None
    assert not p._event.is_set()
    assert not p.wait(0.1)
    assert run.call_count == 0

    p.run()
    run.assert_called_once_with(p._resolve, p._reject)
    assert p._state == S.RESOLVED
    assert p._value == 2
    assert p._event.is_set()
    assert p.wait(0.1)

    run.reset_mock()
    p.run()
    assert run.call_count == 0


def test_promise_thread():
    def run(resolve, _):
        sleep(0.25)
        resolve(3)
    run = Mock(wraps=run)
    p = Promise(run, T.THREAD)

    assert p._state == S.PENDING
    assert p._value is None
    assert p._timeout is None
    assert p._thread is not None
    sleep(0.05)
    run.assert_called_once_with(p._resolve, p._reject)
    run.reset_mock()
    assert not p._event.is_set()

    assert not p.wait(0.05)
    assert run.call_count == 0
    assert p._state == S.PENDING
    assert p._value is None
    assert p._timeout is None
    assert p._thread is not None
    assert not p._event.is_set()

    assert p.wait()
    assert run.call_count == 0
    assert p._state == S.RESOLVED
    assert p._value == 3
    assert p._thread is None
    assert p._event.is_set()

    assert p.wait()


def test_promise_state_not_set():
    p = Promise(lambda *_: None, ptype=T.IMMEDIATE)
    assert p._state == S.REJECTED
    assert isinstance(p._value, PromiseStateNotSet)
    assert p._timeout is None
    assert p._thread is None


def test_promise_timeout():
    p = Promise(lambda resolve, _: resolve(0), ptype=T.MANUAL, timeout=0.01)
    p2 = p.then(lambda value: value + 1, timeout=None)
    p2.wait(0.1)
    assert p._state == S.PENDING
    assert p2._state == S.REJECTED
    assert p._value is None
    assert isinstance(p2._value, PromiseTimeout)


def test_promise_catch_error():
    on_resolve = Mock(wraps=lambda _: 1)
    on_reject = Mock(wraps=lambda _: 2)
    p = Promise.reject(0).then(on_resolve, on_reject)
    p.wait()
    on_reject.assert_called_once_with(0)
    assert on_resolve.call_count == 0
    assert p._value == 2
    assert p._state == S.RESOLVED


def test_promise_on_reject():
    on_resolve = Mock(wraps=lambda _: 1)
    on_reject = Mock(wraps=lambda _: Promise.reject(2))
    p = Promise.reject(0).then(on_resolve, on_reject)
    p.wait()
    on_reject.assert_called_once_with(0)
    assert on_resolve.call_count == 0
    assert p._value == 2
    assert p._state == S.REJECTED


def test_promise_on_reject_2():
    on_resolve = Mock(wraps=lambda _: int('x'))
    on_reject = Mock(wraps=lambda _: Promise.reject(2))
    p = Promise.resolve(0).then(on_resolve, on_reject)
    p.wait()
    on_resolve.assert_called_once_with(0)
    assert on_reject.call_count == 0
    assert isinstance(p._value, Exception)
    assert p._state == S.REJECTED


@pytest.mark.parametrize('length,reject_i,error', [
    (1, 0, None),
    (1, 1, None),
    (3, 3, None),
    (4, 0, None),
    (4, 1, None),
    (4, 2, ValueError),
    (4, 3, None)
])
def test_promise_chain_length(length, reject_i, error):
    i = 0
    def run(_=None):
        nonlocal i
        if i == reject_i:
            if error:
                raise error()
            return Promise.reject(-i)
        i += 1
        return i
    run = Mock(wraps=run)
    chain = [Promise.resolve(0)]
    for i_ in range(length):
        chain.append(chain[i_].then(run))
    assert i == 0
    assert run.call_count == 0
    assert [p._state for p in chain[1:]] == [S.PENDING] * length
    assert chain[len(chain) - 1].wait(0.2)
    assert i == reject_i
    assert run.call_count == i if reject_i >= length else i + 1
    assert [p._state for p in chain[1:i + 1]] == [S.RESOLVED] * reject_i
    assert [p._state for p in chain[i + 1:]] == [S.REJECTED] * (length - reject_i)
    assert [p._value for p in chain[1:i + 1]] == list(range(1, reject_i + 1))
    reject_n = length - reject_i
    if error is not None:
        assert [type(p._value) for p in chain[i + 1:]] == [error] * reject_n
    else:
        assert [p._value for p in chain[i + 1:]] == [-i] * reject_n


@pytest.mark.parametrize('length,reject_i,error', [
    (1, 0, None),
    (1, 1, None),
    (3, 3, None),
    (4, 0, None),
    (4, 1, None),
    (4, 2, ValueError),
    (4, 3, None)
])
def test_promise_chain_depth(length, reject_i, error):
    i = 0
    def run(_=None):
        nonlocal i
        if i == reject_i:
            if error:
                raise error()
            return Promise.reject(-i)
        i += 1
        if i < length:
            return Promise.resolve(i).then(run)
        return i
    run = Mock(wraps=run)
    start = Promise.resolve(0)
    chain = start.then(run)
    end = chain.then(lambda _: 10)
    assert i == 0
    assert run.call_count == 0
    assert start._state == S.RESOLVED
    assert chain._state == S.PENDING
    assert end._state == S.PENDING
    assert end.wait(0.2)
    if reject_i >= length:
        assert chain._value == length
        assert end._value == 10
        assert chain._state == S.RESOLVED
        assert end._state == S.RESOLVED
    else:
        if error is not None:
            assert isinstance(chain._value, error)
            assert isinstance(chain._value, error)
        else:
            assert chain._value == -reject_i
            assert end._value == -reject_i
        assert chain._state == S.REJECTED
        assert end._state == S.REJECTED
    assert i == reject_i
    assert run.call_count == i if reject_i >= length else i + 1
    assert start._state == S.RESOLVED
