import re
import math
from random import random


class ParseError(Exception):
    pass

class BinaryOp:
    def __init__(self, expr, op_func, next_op):
        self.expr = re.compile(expr)
        self.op_func = op_func
        self.next_op = next_op

    def __call__(self, s):
        for match in self.expr.finditer(s):
            i, j = match.span()
            x, op, y = s[:i], match.group(), s[j:]
            try:
                x = self.next_op(x)
                y = self(y)
                return self.op_func(op, x, y)
            except ParseError:
                pass
        return self.next_op(s)

class UnaryOp:
    def __init__(self, expr, op_func, next_op):
        if not expr.startswith('^'):
            expr = '^' + expr
        self.expr = re.compile(expr)
        self.op_func = op_func
        self.next_op = next_op

    def __call__(self, s):
        s = s.strip()
        match = self.expr.match(s)
        if match is None:
            return self.next_op(s)
        op, x = match.groups()
        x = self(x)
        return self.op_func(op, x)

class Paren:
    def __init__(self, start, end, next_op):
        self.start = start
        self.end = end
        self.next_op = next_op

    def __call__(self, s):
        s = s.strip()
        if not (s.startswith(self.start) and s.endswith(self.end)):
            raise ParseError(s)
        return self.next_op(s[len(self.start):-len(self.end)])

class Const:
    def __init__(self, next_op):
        self.next_op = next_op

    def __call__(self, s):
        s = s.strip()
        s_ = s.lower()
        if s_ == 'e':
            return math.e
        elif s_ == 'pi':
            return math.pi
        elif s_ in ('random', 'rnd'):
            return random()
        try:
            return int(s)
        except ValueError:
            try:
                return float(s)
            except ValueError:
                return self.next_op(s)

def create_functions():
    ret = {
        'abs': abs
    }
    for func in [
            'acosh', 'acos', 'asinh', 'asin', 'atanh', 'atan',
            'ceil', 'cos', 'cosh', 'degrees', 'erfc', 'erf',
            'expm1', 'exp', 'fabs', 'floor', 'fmod', 'frexp',
            'fsum', 'gamma', 'isfinite', 'isinf',
            'isnan', 'lgamma', 'log10',
            'log1p', 'log2', 'log', 'modf', 'radians',
            'sinh', 'sin', 'sqrt', 'tanh', 'tan', 'trunc'
    ]:
        ret[func] = getattr(math, func)
    return ret

def create_safe_eval():
    functions = create_functions()
    function_names = sorted(functions.keys(), reverse=True)

    paren = Paren('(', ')', None)
    const = Const(paren)
    func = UnaryOp(
        '^(%s)(.*)' % '|'.join(function_names),
        (lambda op, x: functions[op](x)),
        const
    )
    un = UnaryOp(
        r'^([+-])(.*)',
        (lambda op, x: -x if op == '-' else x),
        func
    )
    pow_ = BinaryOp(
        r'\^',
        lambda _, x, y: float(x) ** float(y),
        un
    )
    div = BinaryOp(
        r'/',
        (lambda _, x, y: x / y),
        pow_
    )
    mul = BinaryOp(
        r'\*',
        (lambda _, x, y: x * y),
        div
    )
    sub = BinaryOp(
        r'-',
        (lambda _, x, y: x - y),
        mul
    )
    add = BinaryOp(
        r'\+',
        (lambda _, x, y: x + y),
        sub
    )
    expr = add
    paren.next_op = expr
    return expr

safe_eval = create_safe_eval()
