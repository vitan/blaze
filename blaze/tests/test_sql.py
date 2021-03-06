import pytest
from sqlalchemy.exc import OperationalError
from cytoolz import first
from blaze.sql import drop, create_index, resource
from blaze import compute, Table, SQL
from blaze.utils import tmpfile


@pytest.fixture
def sql():
    data = [(1, 2), (10, 20), (100, 200)]
    sql = SQL('sqlite:///:memory:', 'foo', schema='{x: int, y: int}')
    sql.extend(data)
    return sql


def test_column(sql):
    t = Table(sql)

    r = compute(t['x'])
    assert r == [1, 10, 100]
    assert compute(t[['x']]) == [(1,), (10,), (100,)]

    assert compute(t.count()) == 3


def test_drop(sql):
    assert sql.table.exists(sql.engine)
    drop(sql)
    assert not sql.table.exists(sql.engine)


class TestCreateIndex(object):

    def test_create_index(self, sql):
        create_index(sql, 'x', name='idx')
        with pytest.raises(OperationalError):
            create_index(sql, 'x', name='idx')

    def test_create_index_fails(self, sql):
        with pytest.raises(AttributeError):
            create_index(sql, 'z', name='zidx')
        with pytest.raises(ValueError):
            create_index(sql, 'x')
        with pytest.raises(ValueError):
            create_index(sql, 'z')

    def test_create_index_unique(self, sql):
        create_index(sql, 'y', name='y_idx', unique=True)
        assert len(sql.table.indexes) == 1
        idx = first(sql.table.indexes)
        assert idx.unique
        assert idx.columns.y == sql.table.c.y

    def test_composite_index(self, sql):
        create_index(sql, ['x', 'y'], name='idx_xy')
        with pytest.raises(OperationalError):
            create_index(sql, ['x', 'y'], name='idx_xy')

    def test_composite_index_fails(self, sql):
        with pytest.raises(AttributeError):
            create_index(sql, ['z', 'bizz'], name='idx_name')

    def test_composite_index_fails_with_existing_columns(self, sql):
        with pytest.raises(AttributeError):
            create_index(sql, ['x', 'z', 'bizz'], name='idx_name')


def test_register(sql):
    with tmpfile('.db') as fn:
        uri = 'sqlite:///' + fn
        sql = SQL(uri, 'foo', schema='{x: int, y: int}')
        assert isinstance(resource(uri, 'foo'), SQL)
        assert isinstance(resource(uri + '::foo'), SQL)

    sql = SQL('sqlite:///:memory:', 'foo', schema='{x: int, y: int}')
    assert isinstance(resource('sqlite:///:memory:', 'foo',
                               schema='{x: int, y: int}'),
                      SQL)
    assert isinstance(resource('sqlite:///:memory:::foo',
                               schema='{x: int, y: int}'),
                      SQL)
