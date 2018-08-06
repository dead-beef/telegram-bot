from threading import Thread, Event
from enum import IntEnum


class PromiseState(IntEnum):
    RESOLVED = 0
    REJECTED = 1
    PENDING = 2


class PromiseType(IntEnum):
    IMMEDIATE = 0
    LAZY = 1
    THREAD = 2
    MANUAL = 3


class PromiseError(Exception):
    pass

class PromiseTimeout(PromiseError):
    pass

class PromiseStateNotSet(PromiseError):
    pass


class Promise:
    def __init__(self, run, ptype=PromiseType.LAZY, timeout=None):
        self._state = PromiseState.PENDING
        self._value = None
        self._event = Event()
        self._timeout = timeout
        self._thread = None
        self._run = run
        self._type = ptype
        if self._type == PromiseType.IMMEDIATE:
            self.run()
        elif self._type == PromiseType.THREAD:
            self._thread = Thread(target=self.run)
            self._thread.start()

    def _set(self, state, value):
        self._state = state
        self._value = value
        self._event.set()

    def _resolve(self, value):
        if self._state != PromiseState.PENDING:
            raise PromiseError('resolve: not pending (%s)' % self._state)
        return self._set(PromiseState.RESOLVED, value)

    def _reject(self, value):
        if self._state != PromiseState.PENDING:
            raise PromiseError('reject: not pending (%s)' % self._state)
        return self._set(PromiseState.REJECTED, value)

    def run(self):
        if self._state != PromiseState.PENDING:
            return self
        try:
            self._run(self._resolve, self._reject)
            if self._state == PromiseState.PENDING:
                raise PromiseStateNotSet()
        except Exception as ex:
            self._reject(ex)
        return self

    def wait(self, timeout=-1):
        if timeout is not None and timeout < 0:
            timeout = self._timeout
        if self._state == PromiseState.PENDING:
            if self._type == PromiseType.LAZY:
                self.run()
            if self._event.wait(timeout):
                if self._thread is not None:
                    self._thread.join()
                    self._thread = None
                return True
            return False
        return True

    def then(self, on_resolve, on_reject=None, ptype=None, timeout=-1):
        def promise(resolve, reject):
            if not self.wait():
                raise PromiseTimeout()
            state, value = self._state, self._value
            if state == PromiseState.RESOLVED:
                if on_resolve is not None:
                    value = on_resolve(value)
            elif on_reject is not None:
                state = PromiseState.RESOLVED
                value = on_reject(value)
            if isinstance(value, Promise):
                if not value.wait():
                    raise PromiseTimeout()
                state, value = value._state, value._value
            if state == PromiseState.RESOLVED:
                resolve(value)
            else:
                reject(value)
        if ptype is None:
            if self._type == PromiseType.IMMEDIATE:
                ptype = self._type
            else:
                ptype = PromiseType.LAZY
        if timeout is not None and timeout < 0:
            timeout = self._timeout
        return Promise(promise, ptype, timeout)

    def catch(self, on_reject=None, ptype=None, timeout=-1):
        if on_reject is None:
            on_reject = lambda x: x
        return self.then(None, on_reject, ptype, timeout)

    @classmethod
    def resolve(cls, value, ptype=PromiseType.LAZY):
        ret = cls(
            lambda resolve, reject: resolve(value),
            PromiseType.IMMEDIATE
        )
        ret._type = ptype
        return ret

    @classmethod
    def reject(cls, value, ptype=PromiseType.LAZY):
        ret = cls(
            lambda resolve, reject: reject(value),
            PromiseType.IMMEDIATE
        )
        ret._type = ptype
        return ret

    @classmethod
    def wrap(cls, func, *args, ptype=PromiseType.LAZY, **kwargs):
        return cls(
            lambda resolve, reject: resolve(func(*args, **kwargs)),
            ptype
        )
