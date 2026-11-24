"""Value simulation behaviors and a restricted expression evaluator.

Expressions are plain Python expressions restricted to arithmetic, comparisons,
boolean logic, conditional expressions and a whitelist of functions.  Names
refer to objects of the same device (object name with non-identifier chars
replaced by ``_``); other devices are reachable with ``pv("Device", "Object")``.
"""

from __future__ import annotations

import ast
import math
import random as _random
import re
from typing import Any, Callable, Dict, Optional

_ALLOWED_NODES = (
    ast.Expression, ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.Compare, ast.IfExp,
    ast.Call, ast.Name, ast.Load, ast.Constant, ast.Tuple, ast.List,
    ast.And, ast.Or, ast.Not, ast.USub, ast.UAdd,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn,
)


def ident(name: str) -> str:
    """Object name -> expression identifier."""
    s = re.sub(r"\W", "_", name)
    return "_" + s if s[:1].isdigit() else s


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


FUNCTIONS: Dict[str, Any] = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan, "exp": math.exp, "log": math.log,
    "sqrt": math.sqrt, "pi": math.pi, "abs": abs, "min": min, "max": max, "round": round,
    "int": int, "float": float, "bool": bool, "sum": sum, "clamp": _clamp,
    "random": _random.random, "uniform": _random.uniform,
    "noise": lambda a=1.0: _random.uniform(-a, a),
    "gauss": lambda sigma=1.0: _random.gauss(0, sigma),
}


class ExpressionError(ValueError):
    pass


def compile_expr(src: str) -> Callable[[Dict[str, Any]], Any]:
    """Compile a restricted expression; returns fn(names) -> value."""
    try:
        tree = ast.parse(str(src), mode="eval")
    except SyntaxError as e:
        raise ExpressionError(f"syntax error in {src!r}: {e.msg}") from None
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ExpressionError(f"not allowed in expression {src!r}: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise ExpressionError(f"dunder names not allowed in {src!r}")
        if isinstance(node, ast.Call) and not isinstance(node.func, ast.Name):
            raise ExpressionError(f"only plain function calls allowed in {src!r}")
    code = compile(tree, "<expr>", "eval")
    env = {"__builtins__": {}, **FUNCTIONS}

    def run(names: Dict[str, Any]) -> Any:
        return eval(code, env, names)  # noqa: S307 - AST-whitelisted

    return run


class Behavior:
    """Base class: step() returns the new value, or None to leave it unchanged."""

    def __init__(self, spec: Dict[str, Any]):
        self.spec = spec

    def step(self, names: Dict[str, Any], current: float, dt: float) -> Optional[float]:
        raise NotImplementedError


class Sine(Behavior):
    def __init__(self, spec):
        super().__init__(spec)
        self.lo, self.hi = float(spec.get("min", 0)), float(spec.get("max", 100))
        self.period = float(spec.get("period", 60))
        self.phase = float(spec.get("phase", 0))
        self.noise = float(spec.get("noise", 0))

    def step(self, names, current, dt):
        mid, amp = (self.hi + self.lo) / 2, (self.hi - self.lo) / 2
        v = mid + amp * math.sin(2 * math.pi * (names["t"] / self.period) + self.phase)
        return v + (_random.uniform(-self.noise, self.noise) if self.noise else 0)


class Random(Behavior):
    def step(self, names, current, dt):
        return _random.uniform(float(self.spec.get("min", 0)), float(self.spec.get("max", 100)))


class RandomWalk(Behavior):
    def step(self, names, current, dt):
        lo, hi = float(self.spec.get("min", 0)), float(self.spec.get("max", 100))
        step = float(self.spec.get("step", (hi - lo) / 50))
        v = (current if current is not None else (lo + hi) / 2) + _random.uniform(-step, step)
        return _clamp(v, lo, hi)


class Expr(Behavior):
    def __init__(self, spec):
        super().__init__(spec)
        self.fn = compile_expr(spec["expr"])

    def step(self, names, current, dt):
        return self.fn(names)


class Follow(Behavior):
    """First-order lag toward a target expression (e.g. room temperature)."""

    def __init__(self, spec):
        super().__init__(spec)
        self.target = compile_expr(spec["target"])
        self.tau = max(float(spec.get("tau", 60)), 1e-3)
        self.noise = float(spec.get("noise", 0))

    def step(self, names, current, dt):
        target = float(self.target(names))
        cur = target if current is None else float(current)
        v = cur + (target - cur) * (1 - math.exp(-dt / self.tau))
        return v + (_random.uniform(-self.noise, self.noise) if self.noise else 0)


class Counter(Behavior):
    """Integrates a rate expression (units per second), e.g. energy from power."""

    def __init__(self, spec):
        super().__init__(spec)
        self.rate = compile_expr(spec.get("rate", 1))

    def step(self, names, current, dt):
        return float(current or 0) + float(self.rate(names)) * dt


class Pulse(Behavior):
    """Pulse counter for accumulators: adds ``rate`` pulses per second (fractions carried over).

    The accumulator wraps to 0 above its ``max`` (max-pres-value).
    """

    def __init__(self, spec):
        super().__init__(spec)
        self.rate = compile_expr(spec.get("rate", 1))
        self.frac = 0.0

    def step(self, names, current, dt):
        x = max(0.0, float(self.rate(names))) * dt + self.frac
        n = math.floor(x)
        self.frac = x - n
        return int(current or 0) + n


BEHAVIORS = {
    "sine": Sine,
    "random": Random,
    "random_walk": RandomWalk,
    "expr": Expr,
    "follow": Follow,
    "counter": Counter,
    "pulse": Pulse,
}


def make_behavior(spec: Optional[Dict[str, Any]]) -> Optional[Behavior]:
    if not spec:
        return None
    kind = spec.get("type")
    if kind in (None, "none", "static"):
        return None
    cls = BEHAVIORS.get(kind)
    if cls is None:
        raise ValueError(f"unknown behavior type: {kind!r} (known: {', '.join(BEHAVIORS)})")
    try:
        return cls(spec)
    except KeyError as e:
        raise ValueError(f"behavior {kind!r} missing parameter {e}") from None
