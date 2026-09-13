"""Инструменты инлайн-режима: безопасный калькулятор и конвертер валют.

Используются хэндлером инлайн-запросов (handlers.py) и whitelist-middleware
(калькулятор и конвертер доступны даже неактивированным пользователям).
"""

import ast
import operator
import re


class MathError(ValueError):
    """Ошибка вычисления арифметического выражения."""


_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}

# Только цифры и арифметические символы — иначе это не калькулятор
_MATH_RE = re.compile(r"^[\d\s+\-*/%^().,]+$")

# "123 gram rub", "123 gram в rub", "5ton usd", "100 usd to rub"
_CONV_RE = re.compile(
    r"^(\d+(?:[.,]\d+)?)\s*([a-zа-яё$€₽£]{2,})\s+(?:в|to|in|на)?\s*([a-zа-яё$€₽£]{2,})$",
    re.IGNORECASE,
)

# Токены TonAPI с подтвержденными курсами (/v2/rates)
TOKEN_ALIASES = {
    "ton": "ton", "тон": "ton", "toncoin": "ton", "тонкоин": "ton",
    "gram": "gram", "грам": "gram",
    "usdt": "usdt", "юсдт": "usdt",
    "not": "not", "нот": "not",
    "dogs": "dogs", "догс": "dogs",
    "hmstr": "hmstr", "хомяк": "hmstr", "хамстер": "hmstr",
}

FIAT_ALIASES = {
    "usd": "usd", "$": "usd", "доллар": "usd", "долл": "usd",
    "eur": "eur", "€": "eur", "евро": "eur",
    "rub": "rub", "₽": "rub", "руб": "rub", "рубля": "rub", "рублей": "rub",
    "uah": "uah", "₴": "uah", "грн": "uah", "гривна": "uah",
    "kzt": "kzt", "тг": "kzt", "тенге": "kzt",
    "gbp": "gbp", "£": "gbp", "фунт": "gbp",
    "cny": "cny", "юань": "cny",
    "jpy": "jpy", "иена": "jpy", "yen": "jpy",
    "aed": "aed", "дирхам": "aed",
    "try": "try", "лира": "try", "lira": "try",
    "byn": "byn", "белрубль": "byn",
    "pln": "pln", "злотый": "pln",
    "chf": "chf", "франк": "chf",
}


def is_math_query(query: str) -> bool:
    """Похоже ли на арифметическое выражение: хотя бы одна цифра и один оператор."""
    q = query.strip()
    return (
        bool(_MATH_RE.fullmatch(q))
        and any(ch.isdigit() for ch in q)
        and any(ch in "+-*/%^" for ch in q)
    )


def try_calc(expr: str) -> float:
    """Безопасно вычисляет арифметику через AST (без eval)."""
    s = expr.replace("^", "**").replace(",", ".").strip()
    if not s or len(s) > 100:
        raise MathError("слишком длинное выражение")
    try:
        tree = ast.parse(s, mode="eval")
    except (SyntaxError, ValueError):
        raise MathError("не удалось разобрать выражение")
    return _eval_node(tree.body)


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 64:
            raise MathError("слишком большая степень")
        try:
            value = _BIN_OPS[type(node.op)](left, right)
        except ZeroDivisionError:
            raise MathError("деление на ноль")
        except OverflowError:
            raise MathError("слишком большой результат")
        if abs(value) > 1e15:
            raise MathError("слишком большой результат")
        return float(value)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return float(_UNARY_OPS[type(node.op)](_eval_node(node.operand)))
    raise MathError("недопустимое выражение")


def fmt_num(x: float) -> str:
    """Форматирует число с пробелами-разделителями тысяч: 13952.17 -> '13 952.17'."""
    x = float(x)
    if x == int(x) and abs(x) < 1e15:
        return f"{int(x):,}".replace(",", " ")
    decimals = 8 if abs(x) < 0.01 else (4 if abs(x) < 1 else 6)
    s = f"{x:.{decimals}f}".rstrip("0").rstrip(".")
    sign = "-" if s.startswith("-") else ""
    if sign:
        s = s[1:]
    int_part, _, frac = s.partition(".")
    grouped = f"{int(int_part):,}".replace(",", " ") if int_part else "0"
    return sign + grouped + (("." + frac) if frac else "")


def parse_conversion(query: str) -> tuple[float, str, str] | None:
    """'123 gram rub' -> (123.0, 'gram', 'rub'). None — если это не конвертация."""
    q = " ".join(query.strip().split())
    m = _CONV_RE.match(q)
    if not m:
        return None
    try:
        amount = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    return amount, m.group(2).lower(), m.group(3).lower()


def resolve_symbol(word: str) -> tuple[str, str] | None:
    """Слово пользователя -> ('token'|'fiat', символ TonAPI) либо None."""
    w = word.strip().lower()
    if w in TOKEN_ALIASES:
        return ("token", TOKEN_ALIASES[w])
    if w in FIAT_ALIASES:
        return ("fiat", FIAT_ALIASES[w])
    return None


def convert_amount(
    amount: float,
    src: tuple[str, str],
    dst: tuple[str, str],
    rates: dict[str, dict[str, float]],
) -> float | None:
    """Пересчитывает amount из src в dst по курсам TonAPI.

    rates: {символ_токена: {валюта: цена}} (все ключи в нижнем регистре).
    Возвращает None, если нужный курс недоступен (в т.ч. нулевой).
    """

    def tok_price(sym: str, cur: str) -> float | None:
        p = (rates.get(sym) or {}).get(cur)
        return float(p) if p else None

    (s_kind, s_sym), (d_kind, d_sym) = src, dst

    if s_kind == "token" and d_kind == "fiat":
        p = tok_price(s_sym, d_sym)
        return amount * p if p is not None else None
    if s_kind == "fiat" and d_kind == "token":
        p = tok_price(d_sym, s_sym)
        return amount / p if p is not None else None
    if s_kind == "token" and d_kind == "token":
        a = tok_price(s_sym, "usd")
        b = tok_price(d_sym, "usd")
        return amount * a / b if (a is not None and b is not None) else None
    # fiat -> fiat: кросс-курс через TON
    a = tok_price("ton", s_sym)
    b = tok_price("ton", d_sym)
    return amount * b / a if (a is not None and b is not None) else None
