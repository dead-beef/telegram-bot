import math
from inspect import signature


MATH = dict(
    (name, getattr(math, name))
    for name in (
        'acosh', 'acos', 'asinh', 'asin', 'atanh', 'atan',
        'ceil', 'cos', 'cosh', 'degrees', 'erfc', 'erf',
        'expm1', 'exp', 'fabs', 'floor', 'fmod', 'frexp',
        'fsum', 'gamma', 'isfinite', 'isinf',
        'isnan', 'lgamma', 'log10',
        'log1p', 'log2', 'log', 'modf', 'pow', 'radians',
        'sinh', 'sin', 'sqrt', 'tanh', 'tan', 'trunc'
    )
)


def create(db, functions=None):
    if functions is None:
        functions = MATH
    for name, func in functions.items():
        db.create_function(name, len(signature(math.pow).parameters), func)
