""" An abstract Table

>>> accounts = TableSymbol('accounts', '{name: string, amount: int}')
>>> deadbeats = accounts['name'][accounts['amount'] < 0]
"""
from __future__ import absolute_import, division, print_function

from datashape import dshape, DataShape, Record, isdimension, Option
from datashape import coretypes as ct
import datashape
import toolz
from toolz import (concat, partial, first, compose, get, unique, second,
                   isdistinct, frequencies, memoize)
import numpy as np
from . import scalar
from .core import (Expr, path, common_subexpression)
from .expr import (Collection, Projection, projection, Selection, selection, Broadcast,
        broadcast, Label, label, ElemWise)
from .scalar import ScalarSymbol, Number
from .scalar import (Eq, Ne, Lt, Le, Gt, Ge, Add, Mult, Div, Sub, Pow, Mod, Or,
                     And, USub, Not, eval_str, FloorDiv, NumberInterface)
from .predicates import isscalar, iscolumn
from datashape.predicates import isunit
from ..compatibility import _strtypes, builtins, unicode, basestring, map, zip
from ..dispatch import dispatch

from .expr import _expr_child, Field, Symbol

from .expr import (sqrt, sin, cos, tan, sinh, cosh, tanh, acos, acosh, asin,
        asinh, atan, atanh, exp, log, expm1, log10, log1p, radians, degrees,
        ceil, floor, trunc, isnan, Map)

__all__ = '''
TableExpr TableSymbol Projection Selection Broadcast Join
Reduction join sqrt sin cos tan sinh cosh tanh acos acosh asin asinh atan atanh
exp log expm1 log10 log1p radians degrees ceil floor trunc isnan any all sum
min max mean var std count nunique By by Sort Distinct distinct Head head Label
ReLabel relabel Map Apply common_subexpression merge Merge Union selection
projection union broadcast Summary summary'''.split()


class TableExpr(Collection):
    """ Super class for all Table Expressions

    This is not intended to be constructed by users.

    See Also
    --------

    blaze.expr.table.TableSymbol
    """
    __inputs__ = 'child',

    @property
    def dshape(self):
        return datashape.var * self.schema

    @property
    def columns(self):
        return self.names

    @property
    def _name(self):
        if iscolumn(self):
            if isinstance(self.schema[0], Record):
                return self.schema[0].names[0]
            try:
                return self.child._name
            except (AttributeError, ValueError):
                raise ValueError("Can not compute name of table")
        else:
            raise ValueError("Column is un-named, name with col.label('aname')")


class TableSymbol(TableExpr, Symbol):
    """ A Symbol for Tabular data

    This is a leaf in the expression tree

    Examples
    --------

    >>> accounts = TableSymbol('accounts',
    ...                        '{name: string, amount: int, id: int}')
    >>> accounts['amount'] + 1
    accounts['amount'] + 1

    We define a TableSymbol with a name like ``accounts`` and the datashape of
    a single row, called a schema.
    """
    __slots__ = '_name', 'dshape'
    __inputs__ = ()

    def __init__(self, name, dshape=None):
        self._name = name
        if isinstance(dshape, _strtypes):
            dshape = datashape.dshape(dshape)
        if not isdimension(dshape[0]):
            dshape = datashape.var * dshape
        self.dshape = dshape

    def __str__(self):
        return self._name

    def resources(self):
        return dict()

    @property
    def schema(self):
        return self.dshape.subshape[0]

    def get_field(self, fieldname):
        return Field(self, fieldname)


class ColumnSyntaxMixin(object):
    """ Syntax bits for table expressions of column shape """

    @property
    def column(self):
        # For backwards compatibility
        return self._name

    def __eq__(self, other):
        return broadcast(Eq, self, other)

    def __add__(self, other):
        return broadcast(Add, self, other)

    def __radd__(self, other):
        return broadcast(Add, other, self)

    def __mul__(self, other):
        return broadcast(Mult, self, other)

    def __rmul__(self, other):
        return broadcast(Mult, other, self)

    def __div__(self, other):
        return broadcast(Div, self, other)

    def __rdiv__(self, other):
        return broadcast(Div, other, self)

    __truediv__ = __div__
    __rtruediv__ = __rdiv__

    def __floordiv__(self, other):
        return broadcast(FloorDiv, self, other)

    def __rfloordiv__(self, other):
        return broadcast(FloorDiv, other, self)

    def __sub__(self, other):
        return broadcast(Sub, self, other)

    def __rsub__(self, other):
        return broadcast(Sub, other, self)

    def __pow__(self, other):
        return broadcast(Pow, self, other)

    def __rpow__(self, other):
        return broadcast(Pow, other, self)

    def __mod__(self, other):
        return broadcast(Mod, self, other)

    def __rmod__(self, other):
        return broadcast(Mod, other, self)

    def __or__(self, other):
        return broadcast(Or, self, other)

    def __ror__(self, other):
        return broadcast(Or, other, self)

    def __and__(self, other):
        return broadcast(And, self, other)

    def __rand__(self, other):
        return broadcast(And, other, self)

    def __neg__(self):
        return broadcast(USub, self)

    def __invert__(self):
        return broadcast(Not, self)


def unpack(l):
    if isinstance(l, (tuple, list, set)) and len(l) == 1:
        return next(iter(l))
    else:
        return l


class Join(TableExpr):
    """ Join two tables on common columns

    Parameters
    ----------
    lhs : TableExpr
    rhs : TableExpr
    on_left : string
    on_right : string

    Examples
    --------

    >>> names = TableSymbol('names', '{name: string, id: int}')
    >>> amounts = TableSymbol('amounts', '{amount: int, id: int}')

    Join tables based on shared column name
    >>> joined = join(names, amounts, 'id')

    Join based on different column names
    >>> amounts = TableSymbol('amounts', '{amount: int, acctNumber: int}')
    >>> joined = join(names, amounts, 'id', 'acctNumber')

    See Also
    --------

    blaze.expr.table.Merge
    blaze.expr.table.Union
    """
    __slots__ = 'lhs', 'rhs', '_on_left', '_on_right', 'how'
    __inputs__ = 'lhs', 'rhs'

    @property
    def on_left(self):
        if isinstance(self._on_left, tuple):
            return list(self._on_left)
        else:
            return self._on_left

    @property
    def on_right(self):
        if isinstance(self._on_right, tuple):
            return list(self._on_right)
        else:
            return self._on_right

    @property
    def schema(self):
        """

        Examples
        --------

        >>> t = TableSymbol('t', '{name: string, amount: int}')
        >>> s = TableSymbol('t', '{name: string, id: int}')

        >>> join(t, s).schema
        dshape("{ name : string, amount : int32, id : int32 }")

        >>> join(t, s, how='left').schema
        dshape("{ name : string, amount : int32, id : ?int32 }")
        """
        option = lambda dt: dt if isinstance(dt, Option) else Option(dt)

        joined = [[name, dt] for name, dt in self.lhs.schema[0].parameters[0]
                        if name in self.on_left]

        left = [[name, dt] for name, dt in self.lhs.schema[0].parameters[0]
                           if name not in self.on_left]

        right = [[name, dt] for name, dt in self.rhs.schema[0].parameters[0]
                            if name not in self.on_right]

        if self.how in ('right', 'outer'):
            left = [[name, option(dt)] for name, dt in left]
        if self.how in ('left', 'outer'):
            right = [[name, option(dt)] for name, dt in right]

        return dshape(Record(joined + left + right))


def join(lhs, rhs, on_left=None, on_right=None, how='inner'):
    if not on_left and not on_right:
        on_left = on_right = unpack(list(sorted(
            set(lhs.names) & set(rhs.names),
            key=lhs.names.index)))
    if not on_right:
        on_right = on_left
    if isinstance(on_left, tuple):
        on_left = list(on_left)
    if isinstance(on_right, tuple):
        on_right = list(on_right)
    if get(on_left, lhs.schema[0]) != get(on_right, rhs.schema[0]):
        raise TypeError("Schema's of joining columns do not match")
    _on_left = tuple(on_left) if isinstance(on_left, list) else on_left
    _on_right = (tuple(on_right) if isinstance(on_right, list)
                        else on_right)

    how = how.lower()
    if how not in ('inner', 'outer', 'left', 'right'):
        raise ValueError("How parameter should be one of "
                         "\n\tinner, outer, left, right."
                         "\nGot: %s" % how)

    return Join(lhs, rhs, _on_left, _on_right, how)


join.__doc__ = Join.__doc__

class Reduction(NumberInterface):
    """ A column-wise reduction

    Blaze supports the same class of reductions as NumPy and Pandas.

        sum, min, max, any, all, mean, var, std, count, nunique

    Examples
    --------

    >>> t = TableSymbol('t', '{name: string, amount: int, id: int}')
    >>> e = t['amount'].sum()

    >>> data = [['Alice', 100, 1],
    ...         ['Bob', 200, 2],
    ...         ['Alice', 50, 3]]

    >>> from blaze.compute.python import compute
    >>> compute(e, data)
    350
    """
    __slots__ = 'child',
    dtype = None

    @property
    def dshape(self):
        return dshape(self.dtype)

    @property
    def symbol(self):
        return type(self).__name__

    @property
    def _name(self):
        try:
            return self.child._name + '_' + type(self).__name__
        except (AttributeError, ValueError, TypeError):
            return type(self).__name__



class any(Reduction):
    dtype = ct.bool_

class all(Reduction):
    dtype = ct.bool_

class sum(Reduction, Number):
    @property
    def dtype(self):
        schema = self.child.schema[0]
        if isinstance(schema, Record) and len(schema.types) == 1:
            return first(schema.types)
        else:
            return schema

class max(Reduction, Number):
    @property
    def dtype(self):
        schema = self.child.schema[0]
        if isinstance(schema, Record) and len(schema.types) == 1:
            return first(schema.types)
        else:
            return schema

class min(Reduction, Number):
    @property
    def dtype(self):
        schema = self.child.schema[0]
        if isinstance(schema, Record) and len(schema.types) == 1:
            return first(schema.types)
        else:
            return schema

class mean(Reduction, Number):
    dtype = ct.real

class var(Reduction, Number):
    """Variance

    Parameters
    ----------
    child : Expr
        An expression
    unbiased : bool, optional
        Compute an unbiased estimate of the population variance if this is
        ``True``. In NumPy and pandas, this parameter is called ``ddof`` (delta
        degrees of freedom) and is equal to 1 for unbiased and 0 for biased.
    """
    __slots__ = 'child', 'unbiased'

    dtype = ct.real

    def __init__(self, child, unbiased=False):
        super(var, self).__init__(child, unbiased)

class std(Reduction, Number):
    """Standard Deviation

    Parameters
    ----------
    child : Expr
        An expression
    unbiased : bool, optional
        Compute the square root of an unbiased estimate of the population
        variance if this is ``True``.

        .. warning::

            This does *not* return an unbiased estimate of the population
            standard deviation.

    See Also
    --------
    var
    """
    __slots__ = 'child', 'unbiased'

    dtype = ct.real

    def __init__(self, child, unbiased=False):
        super(std, self).__init__(child, unbiased)

class count(Reduction, Number):
    dtype = ct.int_

class nunique(Reduction, Number):
    dtype = ct.int_


class Summary(Expr):
    """ A collection of named reductions

    Examples
    --------

    >>> t = TableSymbol('t', '{name: string, amount: int, id: int}')
    >>> expr = summary(number=t.id.nunique(), sum=t.amount.sum())

    >>> data = [['Alice', 100, 1],
    ...         ['Bob', 200, 2],
    ...         ['Alice', 50, 1]]

    >>> from blaze.compute.python import compute
    >>> compute(expr, data)
    (2, 350)
    """
    __slots__ = 'child', 'names', 'values'

    @property
    def dshape(self):
        return dshape(Record(list(zip(self.names,
                                      [v.dtype for v in self.values]))))

    def __str__(self):
        return 'summary(' + ', '.join('%s=%s' % (name, str(val))
                for name, val in zip(self.names, self.values)) + ')'


def summary(**kwargs):
    items = sorted(kwargs.items(), key=first)
    names = tuple(map(first, items))
    values = tuple(map(toolz.second, items))
    child = common_subexpression(*values)

    if len(kwargs) == 1 and isscalar(child):
        while isscalar(child):
            children = [i for i in child.inputs if isinstance(i, Expr)]
            if len(children) == 1:
                child = children[0]
            else:
                raise ValueError()

    return Summary(child, names, values)


summary.__doc__ = Summary.__doc__


def _names_and_types(expr):
    schema = expr.dshape.measure
    if isinstance(schema, Option):
        schema = schema.ty
    if isinstance(schema, Record):
        return schema.names, schema.types
    if isinstance(schema, Unit):
        return [expr._name], [expr.dshape.measure]
    raise ValueError("Unable to determine name and type of %s" % expr)


class By(TableExpr):
    """ Split-Apply-Combine Operator

    Examples
    --------

    >>> t = TableSymbol('t', '{name: string, amount: int, id: int}')
    >>> e = by(t['name'], t['amount'].sum())

    >>> data = [['Alice', 100, 1],
    ...         ['Bob', 200, 2],
    ...         ['Alice', 50, 3]]

    >>> from blaze.compute.python import compute
    >>> sorted(compute(e, data))
    [('Alice', 150), ('Bob', 200)]
    """

    __slots__ = 'grouper', 'apply'

    @property
    def child(self):
        return common_subexpression(self.grouper, self.apply)

    @property
    def schema(self):
        grouper_names, grouper_types = _names_and_types(self.grouper)
        apply_names, apply_types = _names_and_types(self.apply)

        names = grouper_names + apply_names
        types = grouper_types + apply_types

        return dshape(Record(list(zip(names, types))))


@dispatch(Expr, (Summary, Reduction))
def by(grouper, apply):
    return By(grouper, apply)


@dispatch(Expr)
def by(grouper, **kwargs):
    return By(grouper, summary(**kwargs))


def count_values(expr, sort=True):
    """
    Count occurrences of elements in this column

    Sort by counts by default
    Add ``sort=False`` keyword to avoid this behavior.
    """
    result = by(expr, count=expr.count())
    if sort:
        result = result.sort('count', ascending=False)
    return result


class Sort(TableExpr):
    """ Table in sorted order

    Examples
    --------

    >>> accounts = TableSymbol('accounts', '{name: string, amount: int}')
    >>> accounts.sort('amount', ascending=False).schema
    dshape("{ name : string, amount : int32 }")

    Some backends support sorting by arbitrary rowwise tables, e.g.

    >>> accounts.sort(-accounts['amount']) # doctest: +SKIP
    """
    __slots__ = 'child', '_key', 'ascending'

    @property
    def schema(self):
        return self.child.schema

    @property
    def key(self):
        if isinstance(self._key, tuple):
            return list(self._key)
        else:
            return self._key

    def _len(self):
        return self.child._len()


def sort(child, key=None, ascending=True):
    """ Sort table

    Parameters
    ----------
    key: string, list of strings, TableExpr
        Defines by what you want to sort.  Either:
            A single column string, ``t.sort('amount')``
            A list of column strings, ``t.sort(['name', 'amount'])``
            A Table Expression, ``t.sort(-t['amount'])``
    ascending: bool
        Determines order of the sort
    """
    if isinstance(key, list):
        key = tuple(key)
    if key is None:
        key = child.names[0]
    return Sort(child, key, ascending)


class Distinct(TableExpr):
    """
    Removes duplicate rows from the table, so every row is distinct

    Examples
    --------

    >>> t = TableSymbol('t', '{name: string, amount: int, id: int}')
    >>> e = distinct(t)

    >>> data = [('Alice', 100, 1),
    ...         ('Bob', 200, 2),
    ...         ('Alice', 100, 1)]

    >>> from blaze.compute.python import compute
    >>> sorted(compute(e, data))
    [('Alice', 100, 1), ('Bob', 200, 2)]
    """
    __slots__ = 'child',

    @property
    def schema(self):
        return self.child.schema

    @property
    def names(self):
        return self.child.names


def distinct(expr):
    return Distinct(expr)


class Head(TableExpr):
    """ First ``n`` elements of table

    Examples
    --------

    >>> accounts = TableSymbol('accounts', '{name: string, amount: int}')
    >>> accounts.head(5).dshape
    dshape("5 * { name : string, amount : int32 }")
    """
    __slots__ = 'child', 'n'

    @property
    def schema(self):
        return self.child.schema

    @property
    def dshape(self):
        return self.n * self.schema

    def _len(self):
        return builtins.min(self.child._len(), self.n)


def head(child, n=10):
    return Head(child, n)

head.__doc__ = Head.__doc__


class ReLabel(ElemWise):
    """
    Table with same content but with new labels

    Examples
    --------

    >>> accounts = TableSymbol('accounts', '{name: string, amount: int}')
    >>> accounts.schema
    dshape("{ name : string, amount : int32 }")
    >>> accounts.relabel({'amount': 'balance'}).schema
    dshape("{ name : string, balance : int32 }")

    See Also
    --------

    blaze.expr.table.Label
    """
    __slots__ = 'child', 'labels'

    @property
    def schema(self):
        subs = dict(self.labels)
        d = self.child.dshape.measure.dict

        return DataShape(Record([[subs.get(name, name), dtype]
            for name, dtype in self.child.dshape.measure.parameters[0]]))


def relabel(child, labels):
    if isinstance(labels, dict):  # Turn dict into tuples
        labels = tuple(sorted(labels.items()))
    if isunit(child.dshape.measure):
        if child._name == labels[0][0]:
            return child.label(labels[0][1])
        else:
            return child
    return ReLabel(child, labels)

relabel.__doc__ = ReLabel.__doc__


class Apply(TableExpr):
    """ Apply an arbitrary Python function onto a Table

    Examples
    --------

    >>> t = TableSymbol('t', '{name: string, amount: int}')
    >>> h = Apply(hash, t)  # Hash value of resultant table

    Optionally provide extra datashape information

    >>> h = Apply(hash, t, dshape='real')

    Apply brings a function within the expression tree.
    The following transformation is often valid

    Before ``compute(Apply(f, expr), ...)``
    After  ``f(compute(expr, ...)``

    See Also
    --------

    blaze.expr.table.Map
    """
    __slots__ = 'child', 'func', '_dshape'

    def __init__(self, func, child, dshape=None):
        self.child = child
        self.func = func
        self._dshape = dshape

    @property
    def schema(self):
        if isdimension(self.dshape[0]):
            return self.dshape.subshape[0]
        else:
            raise TypeError("Non-tabular datashape, %s" % self.dshape)

    @property
    def dshape(self):
        if self._dshape:
            return dshape(self._dshape)
        else:
            raise NotImplementedError("Datashape of arbitrary Apply not defined")


def merge(*tables):
    # Get common sub expression
    try:
        child = common_subexpression(*tables)
    except:
        raise ValueError("No common sub expression found for input tables")

    result = Merge(child, tables)

    if not isdistinct(result.names):
        raise ValueError("Repeated columns found: " + ', '.join(k for k, v in
            frequencies(result.names).items() if v > 1))

    return result


def schema_concat(exprs):
    """ Concatenate schemas together.  Supporting both Records and Units

    In the case of Units, the name is taken from expr.name
    """
    names, values = [], []
    for c in exprs:
        if isinstance(c.schema[0], Record):
            names.extend(c.schema[0].names)
            values.extend(c.schema[0].types)
        elif isinstance(c.schema[0], Unit):
            names.append(c._name)
            values.append(c.schema[0])
        else:
            raise TypeError("All schemas must have Record or Unit shape."
                            "\nGot %s" % c.schema[0])
    return dshape(Record(list(zip(names, values))))


class Merge(ElemWise):
    """ Merge the columns of many Tables together

    Must all descend from same table via ElemWise operations

    Examples
    --------

    >>> accounts = TableSymbol('accounts', '{name: string, amount: int}')

    >>> newamount = (accounts['amount'] * 1.5).label('new_amount')

    >>> merge(accounts, newamount).names
    ['name', 'amount', 'new_amount']

    See Also
    --------

    blaze.expr.table.Union
    blaze.expr.table.Join
    """
    __slots__ = 'child', 'children'

    @property
    def schema(self):
        return schema_concat(self.children)

    @property
    def names(self):
        return list(concat(child.names for child in self.children))

    def subterms(self):
        yield self
        for i in self.children:
            for node in i.subterms():
                yield node

    def get_field(self, key):
        for child in self.children:
            if key in child.names:
                if iscolumn(child):
                    return child
                else:
                    return child[key]

    def project(self, key):
        if not isinstance(key, (tuple, list)):
            raise TypeError("Expected tuple or list, got %s" % key)
        return merge(*[self[c] for c in key])

    def leaves(self):
        return list(unique(concat(i.leaves() for i in self.children)))


class Union(TableExpr):
    """ Merge the rows of many Tables together

    Must all have the same schema

    Examples
    --------

    >>> usa_accounts = TableSymbol('accounts', '{name: string, amount: int}')
    >>> euro_accounts = TableSymbol('accounts', '{name: string, amount: int}')

    >>> all_accounts = union(usa_accounts, euro_accounts)
    >>> all_accounts.names
    ['name', 'amount']

    See Also
    --------

    blaze.expr.table.Merge
    blaze.expr.table.Join
    """
    __slots__ = 'children',
    __inputs__ = 'children',

    def subterms(self):
        yield self
        for i in self.children:
            for node in i.subterms():
                yield node

    @property
    def schema(self):
        return self.children[0].schema

    def leaves(self):
        return list(unique(concat(i.leaves() for i in self.children)))


def union(*children):
    schemas = set(child.schema for child in children)
    if len(schemas) != 1:
        raise ValueError("Inconsistent schemas:\n\t%s" %
                            '\n\t'.join(map(str, schemas)))
    return Union(children)


def isnumeric(ds):
    """

    >>> isnumeric('int32')
    True
    >>> isnumeric('{amount: int32}')
    True
    >>> isnumeric('{amount: ?int32}')
    True
    >>> isnumeric('{amount: ?int32}')
    True
    >>> isnumeric('var * {amount: ?int32}')
    False
    """
    if isinstance(ds, str):
        ds = dshape(ds)
    if isinstance(ds, DataShape) and len(ds) == 1:
        ds = ds[0]
    if isinstance(ds, Option):
        return isnumeric(ds.ty)
    if isinstance(ds, Record) and len(ds.names) == 1:
        return isnumeric(ds.types[0])
    return isinstance(ds, Unit) and np.issubdtype(to_numpy_dtype(ds), np.number)

def isboolean(ds):
    if isinstance(ds, str):
        ds = dshape(ds)
    if isinstance(ds, DataShape):
        ds = ds[0]
    return (isinstance(ds, Unit) or isinstance(ds, Record) and
            len(ds.dict) == 1) and 'bool' in str(ds)

def iscolumnds(ds):
    return (len(ds.shape) == 1 and
            isinstance(ds.measure, Unit) or
            isinstance(ds.measure, Record) and len(ds.measure.names) == 1)

def isdimensional(ds):
    """

    >>> isdimensional('5 * int')
    True
    >>> isdimensional('int')
    False
    """
    return isdimension(dshape(ds)[0])

from datashape.predicates import istabular, isdimension, isunit, isrecord
from datashape import Unit, Record, to_numpy_dtype
from .expr import schema_method_list, dshape_method_list
from .expr import isnan

schema_method_list.extend([
    (isboolean, set([any, all])),
    (isnumeric, set([mean, isnan, sum, mean, min, max, std, var])),
    (isunit, set([label, relabel])),
    (isrecord, set([relabel])),
    ])

dshape_method_list.extend([
    (isdimensional, set([distinct, count, nunique, head, sort, count_values, head])),
    ])
