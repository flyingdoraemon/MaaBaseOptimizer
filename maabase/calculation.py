"""Request-local progress, exclusive wall time, and bounded calculation reuse."""
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from functools import wraps
from time import perf_counter

_current = ContextVar('calculation', default=None)


class Calculation:
    def __init__(self, callback=None):
        self.started = self.changed = perf_counter()
        self.current = 'preparing'
        self.detail = '准备干员与设施'
        self.seconds = {}
        self.calls = {}
        self.callback = callback
        self.caches = {}
        self.cache_hits = {}

    def _charge(self):
        now = perf_counter()
        if self.current != 'preparing':
            self.seconds[self.current] = self.seconds.get(self.current, 0) + now - self.changed
        self.changed = now

    def snapshot(self):
        seconds = dict(self.seconds)
        if self.current != 'preparing':
            seconds[self.current] = seconds.get(self.current, 0) + perf_counter() - self.changed
        return {'stage': self.current, 'detail': self.detail,
                'elapsed_seconds': round(perf_counter() - self.started, 3),
                'stage_seconds': {k: round(v, 3) for k, v in seconds.items()},
                'stage_calls': dict(self.calls), 'cache_hits': dict(self.cache_hits)}

    def notify(self):
        if self.callback:
            self.callback(self.snapshot())

    @contextmanager
    def stage(self, name, detail=''):
        self._charge()
        previous = self.current, self.detail
        self.current, self.detail = name, detail
        self.calls[name] = self.calls.get(name, 0) + 1
        self.notify()
        try:
            yield
        finally:
            self._charge()
            self.current, self.detail = previous
            self.notify()

    def candidates(self, identity, context, compute):
        cache = self.caches.setdefault('candidates', OrderedDict())
        # Attribute reads include branch conditions, displayed explanations,
        # and whole mutable mappings. A changed dependency forces evaluation;
        # fields never used by these candidates cannot affect their result.
        for key, (dependencies, value) in reversed(cache.items()):
            if key[0] == identity and all(getattr(context, name) == old for name, old in dependencies.items()):
                cache.move_to_end(key)
                self.cache_hits['candidates'] = self.cache_hits.get('candidates', 0) + 1
                return deepcopy(value)
        tracked = _ReadContext(context)
        value = compute(tracked)
        key = (identity, object())
        cache[key] = ({name: deepcopy(getattr(context, name)) for name in tracked.reads}, deepcopy(value))
        if len(cache) > 96:
            cache.popitem(last=False)
        return value


class _ReadContext:
    """Read-only view used solely while evaluating one candidate population."""
    def __init__(self, context):
        self.context = context
        self.reads = set()

    def __getattr__(self, name):
        self.reads.add(name)
        value = getattr(self.context, name)
        # Context is read-only during an enumeration. Record each dependency
        # once, then use ordinary attribute access for thousands of teams.
        setattr(self, name, value)
        return value

    def public(self):
        data = self.context.public()
        self.reads.update(data)
        return data


def current_calculation():
    return _current.get()


@contextmanager
def stage(name, detail=''):
    tracker = _current.get()
    if tracker:
        with tracker.stage(name, detail):
            yield
    else:
        yield


def timed(name):
    def decorate(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            with stage(name):
                return fn(*args, **kwargs)
        return wrapper
    return decorate


def calculation(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        callback = kwargs.pop('progress', None)
        if _current.get() is not None:
            return fn(*args, **kwargs)
        tracker = Calculation(callback)
        token = _current.set(tracker)
        try:
            tracker.notify()
            result = fn(*args, **kwargs)
            result['performance'] = tracker.snapshot()
            return result
        finally:
            _current.reset(token)
    return wrapper
