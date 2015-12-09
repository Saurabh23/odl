﻿# Copyright 2014, 2015 The ODL development group
#
# This file is part of ODL.
#
# ODL is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# ODL is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with ODL.  If not, see <http://www.gnu.org/licenses/>.

"""Spaces of functions with common domain and range."""

# Imports for common Python 2/3 codebase
from __future__ import print_function, division, absolute_import
from future import standard_library
standard_library.install_aliases()
from builtins import super

# External imports
import numpy as np
from functools import wraps
from inspect import isclass, isfunction
from itertools import product

# ODL imports
from odl.operator.operator import Operator, _dispatch_call_args
from odl.set.sets import RealNumbers, ComplexNumbers, Set, Field
from odl.set.space import LinearSpace, LinearSpaceVector
from odl.util.vectorization import (
    is_valid_input_array, is_valid_input_meshgrid,
    meshgrid_input_order, vecs_from_meshgrid,
    out_shape_from_array, out_shape_from_meshgrid)


__all__ = ('FunctionSet', 'FunctionSetVector',
           'FunctionSpace', 'FunctionSpaceVector')


def _out_of_place_not_impl(x, **kwargs):
    """Dummy function used when out-of-place function is not given."""
    raise NotImplementedError('no out-of-place evaluation method defined.')


def _default_in_place(func, x, out, **kwargs):
    """Default in-place evaluation method."""
    out[:] = func(x, **kwargs)
    return out


def _default_out_of_place(func, dtype, x, **kwargs):
    """Default in-place evaluation method."""
    if is_valid_input_array(x, func.domain.ndim):
        out_shape = out_shape_from_array(x)
    elif is_valid_input_meshgrid(x, func.domain.ndim):
        out_shape = out_shape_from_meshgrid(x)
    else:
        raise TypeError('cannot use in-place method to implement '
                        'out-of-place non-vectorized evaluation.')

    out = np.empty(out_shape, dtype=dtype)
    func(x, out=out, **kwargs)
    return out


def vectorize(dtype=None, outarg='none'):
    """Vectorization decorator for our input parameter pattern.

    The wrapped function must be callable with one positional
    parameter. Keyword arguments are passed through, hence positional
    arguments with defaults can either be left out or passed by keyword,
    but not by position.

    Parameters
    ----------
    dtype : `type` or `str`, optional
        Data type of the output array. Needs to be understood by the
        `numpy.dtype` function. If not provided, a "lazy" vectorization
        is performed, meaning that the results are collected in a
        list instead of an array.
    outarg : {'none', 'positional', 'optional'}
        Type of the output argument of the decorated function for
        in-place evaluation

        'none': No output parameter. This is the default.
        Resulting argspec: ``func(x, **kwargs)``
        Returns: the new array

        'positional': Required argument ``out`` at second position.
        Resulting argspec: ``func(x, out=None, **kwargs)``
        Returns: ``out``

        'optional': optional argument ``out`` with default `None`.
        Resulting argspec: ``func(x, out=None, **kwargs)``
        Returns: ``out`` if it is not `None` otherwise a new array

    Note
    ----
    For ``outarg`` not equal to 'none', the decorated function returns
    the array given as ``out`` argument if it is not `None`.

    Examples
    --------
    Vectorize a step function in the first variable:

    >>> @vectorize(dtype=float)
    ... def step(x):
    ...     return 0 if x[0] <= 0 else 1

    This corresponds to (but is much slower than)

    >>> import numpy as np
    >>> def step_vec(x):
    ...     x0, x1 = x
    ...     # np.broadcast is your friend to determine the output shape
    ...     out = np.zeros(np.broadcast(x0, x1).shape, dtype=x0.dtype)
    ...     idcs = np.where(x0 > 0)
    ...     # Need to throw away the indices from the empty dimensions
    ...     idcs = idcs[0] if len(idcs) > 1 else idcs
    ...     out[idcs] = 1
    ...     return out

    Both versions work for arrays and meshgrids:

    >>> x = np.linspace(-5, 13, 10, dtype=float).reshape((2, 5))
    >>> x  # array representing 5 points in 2d
    array([[ -5.,  -3.,  -1.,   1.,   3.],
           [  5.,   7.,   9.,  11.,  13.]])
    >>> np.array_equal(step(x), step_vec(x))
    True

    >>> x = y = np.linspace(-1, 2, 5)
    >>> mg_sparse = np.meshgrid(x, y, indexing='ij', sparse=True)
    >>> np.array_equal(step(mg_sparse), step_vec(mg_sparse))
    True
    >>> mg_dense = np.meshgrid(x, y, indexing='ij', sparse=False)
    >>> np.array_equal(step(mg_dense), step_vec(mg_dense))
    True

    With output parameter:

    >>> @vectorize(dtype=float, outarg='positional')
    ... def step(x):
    ...     return 0 if x[0] <= 0 else 1
    >>> x = np.linspace(-5, 13, 10, dtype=float).reshape((2, 5))
    >>> out = np.empty(5, dtype=float)
    >>> step(x, out)  # returns out
    array([ 0.,  0.,  0.,  1.,  1.])
    """
    def vect_decorator(func):

        def _vect_wrapper_array(x, out, **kwargs):
            # Assume that x is an ndarray
            if out is None:
                out_shape = out_shape_from_array(x)
                if dtype is None:
                    out = [0] * out_shape[0]
                else:
                    out = np.empty(out_shape, dtype=dtype)

            for i, pt in enumerate(x.T):
                out[i] = func(pt, **kwargs)
            return out

        def _vect_wrapper_meshgrid(x, out, **kwargs):
            if out is None:
                out_shape = out_shape_from_meshgrid(x)
                if dtype is None:
                    out = [0] * out_shape[0]
                else:
                    out = np.empty(out_shape, dtype=dtype)

            order = meshgrid_input_order(x)
            vecs = vecs_from_meshgrid(x, order=order)
            for i, pt in enumerate(product(*vecs)):
                out.flat[i] = func(pt, **kwargs)
            return out

        def _vect_wrapper(x, out, **kwargs):
            # Find out dimension first
            if isinstance(x, np.ndarray):  # array
                if x.ndim == 1:
                    dim = 1
                elif x.ndim == 2:
                    dim = len(x)
                else:
                    raise ValueError('only 1- or 2-dimensional arrays '
                                     'supported.')
            else:  # meshgrid
                dim = len(x)

            if is_valid_input_array(x, dim):
                return _vect_wrapper_array(x, out, **kwargs)
            elif is_valid_input_meshgrid(x, dim):
                return _vect_wrapper_meshgrid(x, out, **kwargs)
            else:
                raise TypeError('invalid vectorized input type.')

        @wraps(func)
        def vect_wrapper_no_out(x, **kwargs):
            if 'out' in kwargs:
                raise TypeError("{}() got an unexpected keyword 'out'."
                                "".format(func.__name__))
            return _vect_wrapper(x, None, **kwargs)

        @wraps(func)
        def vect_wrapper_pos_out(x, out, **kwargs):
            return _vect_wrapper(x, out, **kwargs)

        @wraps(func)
        def vect_wrapper_opt_out(x, out=None, **kwargs):
            return _vect_wrapper(x, out, **kwargs)

        outarg_ = str(outarg).lower()
        if outarg_ not in ('none', 'positional', 'optional'):
            raise ValueError('output arg type {!r} not understood.'
                             ''.format(outarg))

        if outarg_ == 'none':
            return vect_wrapper_no_out
        elif outarg_ == 'positional':
            return vect_wrapper_pos_out
        else:
            return vect_wrapper_opt_out
    return vect_decorator


class FunctionSet(Set):

    """A general set of functions with common domain and range."""

    def __init__(self, domain, range):
        """Initialize a new instance.

        Parameters
        ----------
        domain : `Set`
            The domain of the functions.
        range : `Set`
            The range of the functions.
        """
        if not isinstance(domain, Set):
            raise TypeError('domain {!r} not a `Set` instance.'.format(domain))

        if not isinstance(range, Set):
            raise TypeError('range {!r} not a `Set` instance.'.format(range))

        self._domain = domain
        self._range = range

    @property
    def domain(self):
        """Common domain of all functions in this set."""
        return self._domain

    @property
    def range(self):
        """Common range of all functions in this set."""
        return self._range

    def element(self, fcall=None, vectorized=True):
        """Create a `FunctionSet` element.

        Parameters
        ----------
        fcall : `callable`, optional
            The actual instruction for out-of-place evaluation.
            It must return an `range` element or a
            `numpy.ndarray` of such (vectorized call).

            If fcall is a `FunctionSetVector`, it is wrapped
            as a new `FunctionSetVector`.

        vectorized : bool, optional
            Whether the function supports vectorized evaluation

        Returns
        -------
        element : `FunctionSetVector`
            The new element created

        See also
        --------
        TensorGrid.meshgrid : efficient grids for function
            evaluation
        """
        if not callable(fcall):
            raise TypeError('function {!r} is not callable.'.format(fcall))

        if not vectorized:
            fcall = vectorize(fcall, outarg='optional')

        return self.element_type(self, fcall)

    def __eq__(self, other):
        """Return ``self == other``.

        Returns
        -------
        equals : `bool`
            `True` if ``other`` is a `FunctionSet` with same
            `FunctionSet.domain` and `FunctionSet.range`,
            `False` otherwise.
        """
        if other is self:
            return True

        return (isinstance(other, FunctionSet) and
                self.domain == other.domain and
                self.range == other.range)

    def __contains__(self, other):
        """Return ``other in self``.

        Returns
        -------
        equals : `bool`
            `True` if ``other`` is a `FunctionSetVector`
            whose `FunctionSetVector.space` attribute
            equals this space, `False` otherwise.
        """
        return (isinstance(other, self.element_type) and
                self == other.space)

    def __repr__(self):
        """Return ``repr(self)``."""
        return '{}({!r}, {!r})'.format(self.__class__.__name__,
                                       self.domain, self.range)

    def __str__(self):
        """Return ``str(self)``."""
        return '{}({}, {})'.format(self.__class__.__name__,
                                   self.domain, self.range)

    @property
    def element_type(self):
        """ `FunctionSetVector` """
        return FunctionSetVector


class FunctionSetVector(Operator):

    """Representation of a `FunctionSet` element."""

    def __init__(self, fset, fcall):
        """Initialize a new instance.

        Parameters
        ----------
        fset : `FunctionSet`
            The set of functions this element lives in
        fcall : `callable`
            The actual instruction for out-of-place evaluation.
            It must return an `FunctionSet.range` element or a
            `numpy.ndarray` of such (vectorized call).
        """
        self._space = fset
        super().__init__(self._space.domain, self._space.range, linear=False)

        # Determine which type of implementation fcall is
        if isinstance(fcall, FunctionSetVector):
            call_has_out, call_out_optional, _ = _dispatch_call_args(
                bound_call=fcall._call)
        elif isinstance(fcall, np.ufunc):
            if fcall.nin != 1:
                raise ValueError('cannot use `ufunc` with more than one '
                                 'input parameter.')
            call_has_out = call_out_optional = True
        elif isfunction(fcall):
            call_has_out, call_out_optional, _ = _dispatch_call_args(
                unbound_call=fcall)
        elif isclass(fcall):
            call_has_out, call_out_optional, _ = _dispatch_call_args(
                bound_call=fcall.__call__)
        else:
            raise TypeError('callable type {!r} not understood.')

        self._call_has_out = call_has_out
        self._call_out_optional = call_out_optional

        if not call_has_out:
            # Out-of-place only
            def ip_wrapper(func):
                @wraps(func)
                def wrapper(x, out, **kwargs):
                    return func(self, x, out, **kwargs)
                return wrapper

            self._call_in_place = ip_wrapper(_default_in_place)
            self._call_out_of_place = fcall
        elif call_out_optional:
            # Dual-use
            self._call_in_place = self._call_out_of_place = fcall
        else:
            # In-place only
            self._call_in_place = fcall
            # No way to safely determine a data type for the output array,
            # therefore not out-of-place default applicable
            self._call_out_of_place = _out_of_place_not_impl

    @property
    def space(self):
        """The space or set this function belongs to."""
        return self._space

    def _call(self, x, out=None, **kwargs):
        """Raw evaluation method."""
        if out is None:
            out = self._call_out_of_place(x, **kwargs)
        else:
            self._call_in_place(x, out=out, **kwargs)
        return out

    def __call__(self, x, out=None, **kwargs):
        """Out-of-place evaluation.

        Parameters
        ----------
        x : object
            Input argument for the function evaluation. Conditions
            on `x` depend on vectorization:

            `False` : ``x`` must be a domain element

            `True` : ``x`` must be a `numpy.ndarray` with shape
            ``(d, N)``, where ``d`` is the number of dimensions of
            the function domain
            OR
            `x` is a sequence of `numpy.ndarray` with length
            `space.ndim`, and the arrays can be broadcast
            against each other.

        out : `numpy.ndarray`, optional
            Output argument holding the result of the function
            evaluation, can only be used for vectorized
            functions. Its shape must be equal to
            `np.broadcast(*x).shape`.
            If `out` is given, it is returned.

        kwargs : {'vec_bounds_check'}
            'bounds_check' : bool
                Whether or not to check if all input points lie in
                the function domain. For vectorized evaluation,
                this requires the domain to implement
                `contains_all`.

                Default: `True`

        Returns
        -------
        out : range element or array of elements
            Result of the function evaluation

        Raises
        ------
        TypeError
            If `x` is not a valid vectorized evaluation argument

            If `out` is not a range element or a `numpy.ndarray`
            of range elements

        ValueError
            If evaluation points fall outside the valid domain
        """
        vec_bounds_check = kwargs.pop('vec_bounds_check', True)
        if vec_bounds_check and not hasattr(self.domain, 'contains_all'):
            raise AttributeError('vectorized bounds check not possible for '
                                 'domain {}, missing `contains_all()` '
                                 'method.'.format(self.domain))

        # A. Pre-checks and preparations
        # 1. - x = domain element (1), array (2), meshgrid (3)
        #    - make x a (d, 1) array; set a flag that output shall be
        #    scalar; apply case 2a2
        #    - out_shape = (x.shape[1],)
        # 1a3. out_shape = (x[0].shape[1],) if ndim == 1 else
        #      np.broadcast(*x).shape
        # 2a. (cont.) If vec_bounds_check, check domain.contains_all(x)
        # 2b. x in domain? -> yes ok, no error; out is None? yes -> ok,
        #     no -> error
        #
        # B. Evaluation and post-checks
        # 1. out is None? (a/b)
        # 1a. out = call(x)
        # 1a1. out.shape == out_shape? -> error if no
        #      If vec_bounds_check, check range.contains_all(out)
        # 2b. vectorized? (1/2)
        # 2b1. out is array and out.shape == out_shape? -> error if no;
        #     call(x, out=out);
        #     If vec_bounds_check, check range.contains_all(out)
        # 2b2. error (out given but not vectorized)

        # Make single input value an element if possible and use the
        # vectorized array case; if not possible, just go on
        if x not in self.domain:
            try:
                x = self.domain.element(x)
                x = np.atleast_2d(x).T  # make a (d, 1) array
                scalar_out = (out is None)
            except (TypeError, ValueError):
                scalar_out = False

        # vectorized 1: array
        if is_valid_input_array(x, self.domain.ndim):
            if self.domain.ndim == 1:
                if x.ndim == 2:
                    x = x[0]
                out_shape = x.shape
            else:
                out_shape = (x.shape[1],)

        # vectorized 2: meshgrid
        elif is_valid_input_meshgrid(x, self.domain.ndim):
            # Broadcasting fails for only one vector (ndim == 1)
            if self.domain.ndim == 1:
                x = x[0]
                out_shape = x.shape
            else:
                out_shape = np.broadcast(*x).shape
        else:
            raise TypeError('argument {!r} not a valid vectorized '
                            'input. Expected an element of the domain '
                            '{dom}, a ({dom.ndim}, n) array '
                            'or a length-{dom.ndim} meshgrid sequence.'
                            ''.format(x, dom=self.domain))

        if vec_bounds_check:
            if not self.domain.contains_all(x):
                raise ValueError('input contains points outside '
                                 'the domain {}.'.format(self.domain))

        if out is None:
            out = self._call(x, **kwargs)

        if out_shape != (1,) and out.shape != out_shape:
            raise ValueError('output shape {} not equal to shape '
                             '{} expected from input.'
                             ''.format(out.shape, out_shape))
                if vec_bounds_check:
                    if not self.range.contains_all(out):
                        raise ValueError('output contains points outside '
                                         'the range {}.'
                                         ''.format(self.domain))
        else:  # out is not None
            if self.vectorized:
                if not isinstance(out, np.ndarray):
                    raise TypeError('output {!r} not a `numpy.ndarray` '
                                    'instance.')
                if out.shape != out_shape:
                    raise ValueError('output shape {} not equal to shape '
                                     '{} expected from input.'
                                     ''.format(out.shape, out_shape))
                self._call(x, out=out, **kwargs)
                if vec_bounds_check:
                    if not self.range.contains_all(out):
                        raise ValueError('output contains points outside '
                                         'the range {}.'
                                         ''.format(self.domain))
            else:  # not self.vectorized
                raise ValueError('output parameter can only be specified '
                                 'for vectorized functions.')

        return out[0] if scalar_out else out

    def assign(self, other):
        """Assign `other` to this vector.

        This is implemented without `lincomb` to ensure that
        `vec == other` evaluates to `True` after
        `vec.assign(other)`.
        """
        if other not in self.space:
            raise TypeError('vector {!r} is not an element of the space '
                            '{} of this vector.'
                            ''.format(other, self.space))
        self._call_in_place = other._call_in_place
        self._call_out_of_place = other._call_out_of_place
        self._call_has_out = other._call_has_out
        self._call_out_optional = other._call_out_optional
        self._vectorized = other.vectorized

    def copy(self):
        """Create an identical (deep) copy of this vector."""
        result = self.space.element()
        result.assign(self)
        return result

    def __eq__(self, other):
        """`vec.__eq__(other) <==> vec == other`.

        Returns
        -------
        equals : `bool`
            `True` if ``other`` is a `FunctionSetVector` with
            ``other.space`` equal to this vector's space and evaluation
            function of ``other`` and this vector is equal. `False`
            otherwise.
        """
        if other is self:
            return True

        if not isinstance(other, FunctionSetVector):
            return False

        # We cannot blindly compare since functions may have been wrapped
        if (self._call_has_out != other._call_has_out or
                self._call_out_optional != other._call_out_optional):
            return False

        if self._call_has_out:
            funcs_equal = self._call_in_place == other._call_in_place
        else:
            funcs_equal = self._call_out_of_place == other._call_out_of_place

        return (self.space == other.space and
                self.vectorized == other.vectorized and
                funcs_equal)

    def __str__(self):
        """Return ``str(self)``"""
        if self._call_has_out:
            func = self._call_in_place
        else:
            func = self._call_out_of_place
        return str(func)  # TODO: better solution?

    def __repr__(self):
        """Return ``repr(self)``"""
        inner_fstr = '{!r}'
        if not self.vectorized:
            inner_fstr += ', vectorized=False'

        if self._call_has_out:
            func = self._call_in_place
        else:
            func = self._call_out_of_place

        inner_str = inner_fstr.format(func)

        return '{!r}.element({})'.format(self.space, inner_str)


class FunctionSpace(FunctionSet, LinearSpace):

    """A vector space of functions."""

    def __init__(self, domain, field=RealNumbers()):
        """Initialize a new instance.

        Parameters
        ----------
        domain : `Set`
            The domain of the functions
        field : `Field`, optional
            The range of the functions.
        """
        if not isinstance(domain, Set):
            raise TypeError('domain {!r} not a Set instance.'.format(domain))

        if not isinstance(field, Field):
            raise TypeError('field {!r} not a `Field` instance.'
                            ''.format(field))

        FunctionSet.__init__(self, domain, field)
        LinearSpace.__init__(self, field)

    def element(self, fcall=None, vectorized=True):
        """Create a `FunctionSpace` element.

        Parameters
        ----------
        fcall : `callable`, optional
            The actual instruction for out-of-place evaluation.
            It must return an `FunctionSet.range` element or a
            `numpy.ndarray` of such (vectorized call).

            If fcall is a `FunctionSetVector`, it is wrapped
            as a new `FunctionSpaceVector`.

        vectorized : bool
            Whether the function supports vectorized evaluation.

        Returns
        -------
        element : `FunctionSpaceVector`
            The new element.
        """
        if fcall is None:
            return self.zero(vectorized=vectorized)
        else:
            return FunctionSet.element(self, fcall, vectorized=vectorized)

    def zero(self, vectorized=True):
        """The function mapping everything to zero.

        Since `lincomb` is slow, we implement this function directly.
        This function is the additive unit in the function space.

        Parameters
        ----------
        vectorized : bool
            Whether or not the function supports vectorized
            evaluation.
        """
        dtype = complex if self.field == ComplexNumbers() else float
        vectorized = bool(vectorized)

        def zero_novec(_):
            """The zero function, non-vectorized."""
            return dtype(0.0)

        def zero_vec(x):
            """The zero function, vectorized."""
            if is_valid_input_meshgrid(x, self.domain.ndim):
                order = meshgrid_input_order(x)
            else:
                order = 'C'

            bcast = np.broadcast(*x)
            return np.zeros(bcast.shape, dtype=dtype, order=order)

        zero_func = zero_vec if vectorized else zero_novec
        return self.element(zero_func, vectorized=vectorized)

    def one(self, vectorized=True):
        """The function mapping everything to one.

        This function is the multiplicative unit in the function space.

        Parameters
        ----------
        vectorized : bool
            Whether or not the function supports vectorized
            evaluation.
        """
        dtype = complex if self.field == ComplexNumbers() else float
        vectorized = bool(vectorized)

        def one_novec(_):
            """The one function, non-vectorized."""
            return dtype(1.0)

        def one_vec(x):
            """The one function, vectorized."""
            if is_valid_input_meshgrid(x, self.domain.ndim):
                order = meshgrid_input_order(x)
            else:
                order = 'C'

            bcast = np.broadcast(*x)
            return np.ones(bcast.shape, dtype=dtype, order=order)

        one_func = one_vec if vectorized else one_novec
        return self.element(one_func, vectorized=vectorized)

    def __eq__(self, other):
        """`s.__eq__(other) <==> s == other`.

        Returns
        -------
        equals : `bool`
            `True` if `other` is a `FunctionSpace` with same `domain`
            and `range`, `False` otherwise.
        """
        if other is self:
            return True

        return (isinstance(other, FunctionSpace) and
                self.domain == other.domain and
                self.range == other.range)

    def _lincomb(self, a, x1, b, x2, out):
        """Raw linear combination of `x1` and `x2`.

        Note
        ----
        The additions and multiplications are implemented via simple
        Python functions, so non-vectorized versions are slow.
        """
        # Store to allow aliasing
        x1_call_oop = x1._call_out_of_place
        x1_call_ip = x1._call_in_place
        x2_call_oop = x2._call_out_of_place
        x2_call_ip = x2._call_in_place

        lincomb_vect = x1.vectorized or x2.vectorized
        dtype = complex if self.field == ComplexNumbers() else float
        # Manually vectorize if necessary. Use out-of-place for both
        if lincomb_vect and not x1.vectorized:
            x1_call_oop = vectorize(dtype, outarg='none')(x1_call_oop)
            x1_call_ip = vectorize(dtype, outarg='positional')(x1_call_oop)
        if lincomb_vect and not x2.vectorized:
            x2_call_oop = vectorize(dtype, outarg='none')(x2_call_oop)
            x2_call_ip = vectorize(dtype, outarg='positional')(x2_call_oop)

        def lincomb_call_out_of_place(x):
            """Linear combination, out-of-place version."""
            # Due to vectorization, at least one call must be made to
            # ensure the correct final shape. The rest is optimized as
            # far as possible.
            if a == 0 and b != 0:
                out = x2_call_oop(x)
                if b != 1:
                    out *= b
            elif b == 0:  # Contains the case a == 0
                out = x1_call_oop(x)
                if a != 1:
                    out *= a
            else:
                out = x1_call_oop(x)
                if a != 1:
                    out *= a
                tmp = x2_call_oop(x)
                if b != 1:
                    tmp *= b
                out += tmp
            return out

        def lincomb_call_in_place(x, out):
            """Linear combination, in-place version."""
            if not isinstance(out, np.ndarray):
                raise TypeError('in-place evaluation only possible if output '
                                'is of type `numpy.ndarray`.')
            if a == 0 and b == 0:
                out *= 0
            elif a == 0 and b != 0:
                x2_call_ip(x, out)
                if b != 1:
                    out *= b
            elif b == 0 and a != 0:
                x1_call_ip(x, out)
                if a != 1:
                    out *= a
            else:
                tmp = np.empty_like(out)
                x1_call_ip(x, out)
                x2_call_ip(x, tmp)
                if a != 1:
                    out *= a
                if b != 1:
                    tmp *= b
                out += tmp
            return out

        def lincomb_call(x, out=None):
            """Linear combination, dual-use version for final use."""
            if out is None:
                return lincomb_call_out_of_place(x)
            else:
                return lincomb_call_in_place(x, out)

        if lincomb_vect:
            out._call_out_of_place = out._call_in_place = lincomb_call
            out._call_has_out = out._call_out_optional = True
        else:
            out._call_out_of_place = lincomb_call_out_of_place
            out._call_in_place = _default_in_place
            out._call_has_out = out._call_out_optional = False

        out._vectorized = lincomb_vect

        return out

    def _multiply(self, x1, x2, out):
        """Raw pointwise multiplication of two functions.

        Notes
        -----
        The multiplication is implemented with a simple Python
        function, so the resulting function object is probably slow.
        """
        x1_call_oop = x1._call_out_of_place
        x1_call_ip = x1._call_in_place
        x2_call_oop = x2._call_out_of_place
        x2_call_ip = x2._call_in_place

        product_vect = x1.vectorized or x2.vectorized
        dtype = complex if self.field == ComplexNumbers() else float
        # Manually vectorize if necessary. Use out-of-place for both
        if product_vect and not x1.vectorized:
            x1_call_oop = vectorize(dtype, outarg='none')(x1_call_oop)
            x1_call_ip = vectorize(dtype, outarg='positional')(x1_call_oop)
        if product_vect and not x2.vectorized:
            x2_call_oop = vectorize(dtype, outarg='none')(x2_call_oop)
            x2_call_ip = vectorize(dtype, outarg='positional')(x2_call_oop)

        def product_call_out_of_place(x):
            """The product out-of-place evaluation function."""
            return x1_call_oop(x) * x2_call_oop(x)

        def product_call_in_place(x, out):
            """The product in-place evaluation function."""
            tmp = np.empty_like(out)
            x1_call_ip(x, out)
            x2_call_ip(x, tmp)
            out *= tmp
            return out

        def product_call(x, out=None):
            """Product, dual-use version for final use."""
            if out is None:
                return product_call_out_of_place(x)
            else:
                return product_call_in_place(x, out)

        if product_vect:
            out._call_out_of_place = out._call_in_place = product_call
            out._call_has_out = out._call_out_optional = True
        else:
            out._call_out_of_place = product_call_out_of_place
            out._call_in_place = _default_in_place
            out._call_has_out = out._call_out_optional = False

        out._vectorized = product_vect

        return out

    def _divide(self, x1, x2, out):
        """Raw pointwise division of two functions."""
        x1_call_oop = x1._call_out_of_place
        x1_call_ip = x1._call_in_place
        x2_call_oop = x2._call_out_of_place
        x2_call_ip = x2._call_in_place

        quotient_vect = x1.vectorized or x2.vectorized
        dtype = complex if self.field == ComplexNumbers() else float
        # Manually vectorize if necessary. Use out-of-place for both
        if quotient_vect and not x1.vectorized:
            x1_call_oop = vectorize(dtype, outarg='none')(x1_call_oop)
            x1_call_ip = vectorize(dtype, outarg='positional')(x1_call_oop)
        if quotient_vect and not x2.vectorized:
            x2_call_oop = vectorize(dtype, outarg='none')(x2_call_oop)
            x2_call_ip = vectorize(dtype, outarg='positional')(x2_call_oop)

        def quotient_call_out_of_place(x):
            """The quotient out-of-place evaluation function."""
            return x1_call_oop(x) / x2_call_oop(x)

        def quotient_call_in_place(x, out):
            """The quotient in-place evaluation function."""
            tmp = np.empty_like(out)
            x1_call_ip(x, out)
            x2_call_ip(x, tmp)
            out /= tmp
            return out

        def quotient_call(x, out=None):
            """Quotient, dual-use version for final use."""
            if out is None:
                return quotient_call_out_of_place(x)
            else:
                return quotient_call_in_place(x, out)

        if quotient_vect:
            out._call_out_of_place = out._call_in_place = quotient_call
            out._call_has_out = out._call_out_optional = True
        else:
            out._call_out_of_place = quotient_call_out_of_place
            out._call_in_place = _default_in_place
            out._call_has_out = out._call_out_optional = False

        out._vectorized = quotient_vect

        return out

    def _scalar_power(self, x, p, out):
        """Raw p-th power of a function, p integer or general scalar."""
        x_call_oop = x._call_out_of_place
        x_call_ip = x._call_in_place

        def pow_posint(x, n):
            """Recursion to calculate the n-th power out-of-place."""
            if isinstance(x, np.ndarray):
                y = x.copy()
                return ipow_posint(y, n)
            else:
                return x ** n

        def ipow_posint(x, n):
            """Recursion to calculate the n-th power in-place."""
            if n == 1:
                return x
            elif n % 2 == 0:
                x *= x
                return ipow_posint(x, n // 2)
            else:
                tmp = x.copy()
                x *= x
                ipow_posint(x, n // 2)
                x *= tmp
                return x

        def power_call_out_of_place(x):
            """The power out-of-place evaluation function."""
            if p == int(p) and p >= 1:
                return pow_posint(x_call_oop(x), int(p))
            else:
                return x_call_oop(x) ** p

        def power_call_in_place(x, out):
            """The power in-place evaluation function."""
            x_call_ip(x, out)
            if p == int(p) and p >= 1:
                return ipow_posint(out, int(p))
            else:
                out **= p
                return out

        def power_call(x, out=None):
            """Power, dual-use version for final use."""
            if out is None:
                return power_call_out_of_place(x)
            else:
                return power_call_in_place(x, out)

        if self.vectorized:
            out._call_out_of_place = out._call_in_place = power_call
            out._call_has_out = out._call_out_optional = True
        else:
            out._call_out_of_place = power_call_out_of_place
            out._call_in_place = _default_in_place
            out._call_has_out = out._call_out_optional = False

        out._vectorized = self.vectorized

        return out

    @property
    def element_type(self):
        """ `FunctionSpaceVector` """
        return FunctionSpaceVector


class FunctionSpaceVector(FunctionSetVector, LinearSpaceVector):

    """Representation of a `FunctionSpace` element."""

    def __init__(self, fspace, fcall=None, vectorized=True):
        """Initialize a new instance.

        Parameters
        ----------
        fspace : `FunctionSpace`
            The set of functions this element lives in
        fcall : `callable`, optional
            The actual instruction for out-of-place evaluation.
            It must return an `FunctionSet.range` element or a
            `numpy.ndarray` of such (vectorized call).
        vectorized : bool
            Whether the function supports vectorized
            evaluation.
        """
        if not isinstance(fspace, FunctionSpace):
            raise TypeError('function space {!r} not a `FunctionSpace` '
                            'instance.'.format(fspace))

        FunctionSetVector.__init__(self, fspace, fcall, vectorized=vectorized)
        if self._call_has_out and not self._call_out_optional:
            # Now we can use a default out-of-place implementation
            dtype = float if fspace.field == RealNumbers() else complex

            def oop_wrapper(func):
                @wraps(func)
                def wrapper(x, **kwargs):
                    return func(self, dtype, x, **kwargs)
                return wrapper

            self._call_out_of_place = oop_wrapper(_default_out_of_place)

    def __pow__(self, p):
        """`f.__pow__(p) <==> f ** p`."""
        out = self.space.element()
        self.space._scalar_power(self, p, out=out)
        return out

    def __ipow__(self, p):
        """`f.__ipow__(p) <==> f **= p`."""
        return self.space._scalar_power(self, p, out=self)


if __name__ == '__main__':
    from doctest import testmod, NORMALIZE_WHITESPACE
    testmod(optionflags=NORMALIZE_WHITESPACE)
