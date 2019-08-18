import math
from itertools import chain


MATH = list(chain.from_iterable(
    ((func, nargs, getattr(math, func)) for func in funcs)
    for nargs, funcs in enumerate((
        (
            'acosh', 'acos', 'asinh', 'asin', 'atanh', 'atan',
            'ceil', 'cos', 'cosh', 'degrees', 'erfc', 'erf',
            'expm1', 'exp', 'fabs', 'floor', 'fmod', 'frexp',
            'fsum', 'gamma', 'isfinite', 'isinf',
            'isnan', 'lgamma', 'log10',
            'log1p', 'log2', 'log', 'modf', 'radians',
            'sinh', 'sin', 'sqrt', 'tanh', 'tan', 'trunc'
        ),
        ('log', 'pow')
    ), 1)
))


def create(db, functions=None):
    if functions is None:
        functions = MATH
    for args in functions:
        db.create_function(*args)
