import pytest

from bot.namespace import Namespace


@pytest.mark.parametrize('test', [
    {},
    {'x': 0, 'y': 1}
])
def test_namespace(test):
    ns = Namespace(**test)
    test['prototype'] = None
    assert ns.__dict__ == test


@pytest.mark.parametrize('test,item,res', [
    ([{}], 'x', Exception),
    ([{'x': 0}], 'x', 0),
    ([{'x': 0, 'y': 1}, {'y': 2}], 'x', 0),
    ([{'x': 0, 'y': 1}, {'y': 2}], 'y', 2),
    ([{'x': 0}, {'y': 1}, {'y': 2}], 'x', 0),
    ([{'x': 0}, {'y': 1}, {'z': 2}], 'y', 1)
])
def test_namespace_getitem_getattr(test, item, res):
    ns = None
    for obj in test:
        ns = Namespace(ns, **obj)
    if isinstance(res, type) and issubclass(res, Exception):
        with pytest.raises(KeyError):
            ns[item]
        with pytest.raises(AttributeError):
            getattr(ns, item)
    else:
        assert ns[item] == res
        assert getattr(ns, item) == res


@pytest.mark.parametrize('test,item,res', [
    ([{}], 'x', False),
    ([{'x': 0}], 'x', True),
    ([{'x': 0, 'y': 1}, {'y': 2}], 'x', False),
    ([{'x': 0, 'y': 1}, {'y': 2}], 'y', True),
    ([{'x': 0}, {'y': 1}, {'y': 2}], 'x', False),
    ([{'x': 0}, {'y': 1}, {'z': 2}], 'z', True)
])
def test_namespace_has_own_property(test, item, res):
    ns = None
    for obj in test:
        ns = Namespace(ns, **obj)
    assert ns.has_own_property(item) == res
