"""Разбор и вычисление математических выражений.

Конвейер разбора::

    tokenize(text) -> [Token]        # лексический разбор
    to_rpn(tokens) -> [Node]         # сортировочная станция -> обратная польская запись
    compile_rpn(rpn) -> callable     # дерево замыканий, принимающее x

Формула разбирается ОДИН раз при создании :class:`Expression`; вычисление
в очередной точке стоит один проход по готовому дереву. Это принципиально
отличается от наивной схемы «разбирать заново на каждой точке графика».

Ошибки в тексте формулы поднимают :class:`ExpressionError` с позицией символа,
чтобы интерфейс мог показать пользователю, где именно он ошибся. Ошибки
области определения (корень из отрицательного, деление на ноль, логарифм
неположительного) ошибками не считаются — они дают NaN, и график в этой
точке просто прерывается.
"""

from __future__ import annotations

import difflib
import math
from dataclasses import dataclass
from typing import Callable, Sequence

NAN = float("nan")

__all__ = [
    "ExpressionError",
    "Expression",
    "tokenize",
    "to_rpn",
    "compile_rpn",
    "FUNCTIONS",
    "BINARY_OPS",
    "CONSTANTS",
]


class ExpressionError(ValueError):
    """Синтаксическая или семантическая ошибка в тексте формулы.

    :param message: текст для пользователя.
    :param position: индекс символа в исходной строке (или ``None``).
    """

    def __init__(self, message: str, position: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.position = position

    def __str__(self) -> str:
        if self.position is None:
            return self.message
        return f"{self.message} (позиция {self.position + 1})"


# --------------------------------------------------------------------------
# Безопасная математика.
#
# Каждая обёртка возвращает NaN там, где функция не определена, вместо того
# чтобы бросать исключение: NaN естественно превращается в разрыв графика,
# а исключение на каждой из тысячи точек стоило бы дорого.
# --------------------------------------------------------------------------


def _guard(value: float) -> float:
    """Отбрасывает бесконечности, чтобы они не ломали расчёт координат."""
    return value if -1e308 < value < 1e308 else NAN


def _div(a: float, b: float) -> float:
    return a / b if b else NAN


def _mod(a: float, b: float) -> float:
    return a % b if b else NAN


def _pow(a: float, b: float) -> float:
    """Возведение в степень без утечки комплексных чисел наружу.

    ``(-8) ** 0.5`` в Python возвращает комплексное число; для графика
    вещественной функции это не значение, а пробел.
    """
    try:
        result = a ** b
    except (ArithmeticError, ValueError):
        return NAN
    if isinstance(result, complex):
        return NAN
    return _guard(result)


def _factorial(a: float) -> float:
    """Факториал через гамма-функцию: определён и для нецелых аргументов.

    Заодно снимает проблему производительности — ``math.factorial(10**6)``
    считается секундами, ``math.gamma`` переполняется уже около 171.
    """
    try:
        return _guard(math.gamma(a + 1.0))
    except (ArithmeticError, ValueError):
        return NAN


def _safe(func: Callable[..., float]):
    """Оборачивает функцию перехватом ошибок области определения."""

    def wrapper(*args: float) -> float:
        try:
            return _guard(func(*args))
        except (ArithmeticError, ValueError):
            return NAN

    return wrapper


def _cot(a: float) -> float:
    t = math.tan(a)
    return 1.0 / t if t else NAN


def _sec(a: float) -> float:
    c = math.cos(a)
    return 1.0 / c if c else NAN


def _csc(a: float) -> float:
    s = math.sin(a)
    return 1.0 / s if s else NAN


def _cbrt(a: float) -> float:
    """Кубический корень, сохраняющий знак: cbrt(-8) = -2."""
    return math.copysign(abs(a) ** (1.0 / 3.0), a)


def _root(n: float, a: float) -> float:
    """Корень n-й степени. Для нечётного n определён и на отрицательных."""
    if n == 0:
        return NAN
    if a < 0:
        if n != int(n) or int(n) % 2 == 0:
            return NAN
        return -(_pow(-a, 1.0 / n))
    return _pow(a, 1.0 / n)


def _sign(a: float) -> float:
    if a != a:  # NaN
        return NAN
    return math.copysign(1.0, a) if a else 0.0


def _frac(a: float) -> float:
    """Дробная часть, сохраняющая знак: frac(-1.25) = -0.25."""
    return math.modf(a)[0]


def _clamp(a: float, low: float, high: float) -> float:
    if low > high:
        low, high = high, low
    return low if a < low else high if a > high else a


def _truthy(value: float) -> bool:
    """Истинность числа: ноль и NaN ложны, остальное истинно."""
    return value == value and value != 0.0


# --------------------------------------------------------------------------
# Словарь языка формул.
#
# Таблицы ниже — единственный источник правды: по ним работает разбор, и по
# ним же строится экран справки. Добавление функции сюда автоматически
# делает её доступной в формулах и описанной в справке.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class BinaryOp:
    """Бинарный оператор: приоритет, ассоциативность и реализация."""

    symbol: str
    precedence: int
    right_assoc: bool
    func: Callable[[float, float], float]
    help: str


@dataclass(frozen=True)
class Function:
    """Именованная функция с проверяемой арностью.

    :param max_args: ``None`` означает произвольное число аргументов.
    """

    name: str
    min_args: int
    max_args: int | None
    func: Callable[..., float]
    help: str
    signature: str = ""

    def accepts(self, count: int) -> bool:
        if count < self.min_args:
            return False
        return self.max_args is None or count <= self.max_args


# Приоритеты. Унарный минус намеренно слабее степени, поэтому -x^2 = -(x^2),
# как принято в математике, а не (-x)^2.
PREC_COMPARE = 1
PREC_ADD = 2
PREC_MUL = 3
PREC_UNARY = 4
PREC_POWER = 5

BINARY_OPS: dict[str, BinaryOp] = {
    op.symbol: op
    for op in (
        BinaryOp("<", PREC_COMPARE, False, lambda a, b: float(a < b), "меньше -> 1 или 0"),
        BinaryOp(">", PREC_COMPARE, False, lambda a, b: float(a > b), "больше -> 1 или 0"),
        BinaryOp("<=", PREC_COMPARE, False, lambda a, b: float(a <= b), "меньше или равно"),
        BinaryOp(">=", PREC_COMPARE, False, lambda a, b: float(a >= b), "больше или равно"),
        BinaryOp("==", PREC_COMPARE, False, lambda a, b: float(a == b), "равно"),
        BinaryOp("!=", PREC_COMPARE, False, lambda a, b: float(a != b), "не равно"),
        BinaryOp("+", PREC_ADD, False, lambda a, b: a + b, "сложение"),
        BinaryOp("-", PREC_ADD, False, lambda a, b: a - b, "вычитание"),
        BinaryOp("*", PREC_MUL, False, lambda a, b: a * b, "умножение"),
        BinaryOp("/", PREC_MUL, False, _div, "деление (на ноль даёт разрыв)"),
        BinaryOp("%", PREC_MUL, False, _mod, "остаток от деления"),
        BinaryOp("^", PREC_POWER, True, _pow, "возведение в степень, правоассоциативно"),
    )
}

CONSTANTS: dict[str, float] = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
    "phi": (1.0 + math.sqrt(5.0)) / 2.0,
}

VARIABLE = "x"


def _lazy_only(*_args: float) -> float:
    """Заглушка для функций, которые compile_rpn обрабатывает особо."""
    raise AssertionError("эта функция должна вычисляться лениво в compile_rpn")


def _fn(name: str, min_args: int, max_args: int | None, func, help_text: str, signature: str = "") -> Function:
    return Function(name, min_args, max_args, func, help_text, signature or f"{name}(x)")


FUNCTIONS: dict[str, Function] = {
    f.name: f
    for f in (
        # Тригонометрия
        _fn("sin", 1, 1, _safe(math.sin), "синус"),
        _fn("cos", 1, 1, _safe(math.cos), "косинус"),
        _fn("tan", 1, 1, _safe(math.tan), "тангенс"),
        _fn("cot", 1, 1, _safe(_cot), "котангенс"),
        _fn("sec", 1, 1, _safe(_sec), "секанс, 1/cos"),
        _fn("csc", 1, 1, _safe(_csc), "косеканс, 1/sin"),
        # Обратная тригонометрия
        _fn("asin", 1, 1, _safe(math.asin), "арксинус, |x| <= 1"),
        _fn("acos", 1, 1, _safe(math.acos), "арккосинус, |x| <= 1"),
        _fn("atan", 1, 1, _safe(math.atan), "арктангенс"),
        _fn("acot", 1, 1, _safe(lambda a: math.pi / 2.0 - math.atan(a)), "арккотангенс"),
        _fn("atan2", 2, 2, _safe(math.atan2), "угол точки (b, a) в радианах", "atan2(y, x)"),
        # Гиперболические
        _fn("sinh", 1, 1, _safe(math.sinh), "гиперболический синус"),
        _fn("cosh", 1, 1, _safe(math.cosh), "гиперболический косинус"),
        _fn("tanh", 1, 1, _safe(math.tanh), "гиперболический тангенс"),
        _fn("asinh", 1, 1, _safe(math.asinh), "обратный гиперболический синус"),
        _fn("acosh", 1, 1, _safe(math.acosh), "обратный гиперболический косинус, x >= 1"),
        _fn("atanh", 1, 1, _safe(math.atanh), "обратный гиперболический тангенс, |x| < 1"),
        # Степени и корни
        _fn("sqrt", 1, 1, _safe(math.sqrt), "квадратный корень, x >= 0"),
        _fn("cbrt", 1, 1, _safe(_cbrt), "кубический корень, определён и для x < 0"),
        _fn("root", 2, 2, _root, "корень n-й степени, для нечётных n работает и на x < 0", "root(n, x)"),
        _fn("exp", 1, 1, _safe(math.exp), "экспонента, e^x"),
        _fn("ln", 1, 1, _safe(math.log), "натуральный логарифм, x > 0"),
        _fn("lg", 1, 1, _safe(math.log10), "десятичный логарифм, x > 0"),
        _fn("log2", 1, 1, _safe(math.log2), "двоичный логарифм, x > 0"),
        _fn("log", 2, 2, _safe(lambda b, a: math.log(a, b)), "логарифм x по основанию b", "log(b, x)"),
        # Округление и знак
        _fn("abs", 1, 1, _safe(abs), "модуль числа"),
        _fn("sign", 1, 1, _sign, "знак: -1, 0 или 1"),
        _fn("floor", 1, 1, _safe(lambda a: float(math.floor(a))), "округление вниз"),
        _fn("ceil", 1, 1, _safe(lambda a: float(math.ceil(a))), "округление вверх"),
        _fn("round", 1, 2, _safe(lambda a, n=0.0: round(a, int(n))), "округление до n знаков", "round(x[, n])"),
        _fn("trunc", 1, 1, _safe(lambda a: float(math.trunc(a))), "отбрасывание дробной части"),
        _fn("frac", 1, 1, _safe(_frac), "дробная часть числа"),
        # Выбор и сравнение
        _fn("min", 1, None, _safe(lambda *args: min(args)), "наименьший из аргументов", "min(a, b, ...)"),
        _fn("max", 1, None, _safe(lambda *args: max(args)), "наибольший из аргументов", "max(a, b, ...)"),
        _fn("clamp", 3, 3, _safe(_clamp), "зажать x в границах [a, b]", "clamp(x, a, b)"),
        _fn("hypot", 2, None, _safe(math.hypot), "длина вектора, sqrt(a^2 + b^2)", "hypot(a, b, ...)"),
        _fn("mod", 2, 2, _mod, "остаток от деления", "mod(a, b)"),
        # Прочее
        _fn("gamma", 1, 1, _safe(math.gamma), "гамма-функция"),
        _fn("deg", 1, 1, _safe(math.degrees), "радианы -> градусы"),
        _fn("rad", 1, 1, _safe(math.radians), "градусы -> радианы"),
        _fn(
            "if",
            3,
            3,
            _lazy_only,  # особый случай: ветви вычисляются лениво, см. compile_rpn
            "если условие истинно, вернуть a, иначе b",
            "if(условие, a, b)",
        ),
    )
}

UNARY_OPS = {"-", "+"}
POSTFIX_OPS = {"!"}


# --------------------------------------------------------------------------
# Лексический разбор
# --------------------------------------------------------------------------

# Кириллические буквы, неотличимые на экране от латинских. Раскладку легко
# не переключить, а сообщение «неизвестное имя 'сos'» без подсказки выглядит
# издевательством: символы выглядят одинаково.
_HOMOGLYPHS = str.maketrans(
    "аАвВеЕкКмМнНоОрРсСтТуУхХіјѕԁ",
    "aABBeEkKmMHHoOpPcCtTyYxXijsd",
)

_TWO_CHAR_OPS = ("<=", ">=", "==", "!=")
_ONE_CHAR_OPS = "+-*/%^<>"
_PUNCTUATION = "(),"


@dataclass(frozen=True)
class Token:
    """Лексема с позицией в исходной строке.

    ``kind`` — одно из ``number``, ``name``, ``op``, ``lparen``, ``rparen``, ``comma``.
    """

    kind: str
    text: str
    pos: int
    value: float = 0.0


def _is_name_start(char: str) -> bool:
    return char.isalpha() or char == "_"


def _is_name_char(char: str) -> bool:
    return char.isalnum() or char == "_"


def _scan_number(text: str, start: int) -> tuple[float, int]:
    """Считывает число, включая ``.5`` и научную запись ``1.2e-3``."""
    i = start
    length = len(text)
    seen_dot = False
    while i < length and (text[i].isdigit() or text[i] == "."):
        if text[i] == ".":
            if seen_dot:
                raise ExpressionError("В числе больше одной точки", i)
            seen_dot = True
        i += 1

    # Экспоненту забираем только если за ней действительно идут цифры,
    # иначе '2e' — это 2 * e (константа), а не оборванное число.
    if i < length and text[i] in "eE":
        j = i + 1
        if j < length and text[j] in "+-":
            j += 1
        if j < length and text[j].isdigit():
            while j < length and text[j].isdigit():
                j += 1
            i = j

    raw = text[start:i]
    if raw in (".",):
        raise ExpressionError("Точка без цифр не является числом", start)
    try:
        return float(raw), i
    except ValueError as exc:  # pragma: no cover - страховка на неожиданный ввод
        raise ExpressionError(f"Не удалось прочитать число '{raw}'", start) from exc


def tokenize(text: str) -> list[Token]:
    """Разбивает текст формулы на лексемы.

    :raises ExpressionError: если встречен недопустимый символ.
    """
    tokens: list[Token] = []
    i = 0
    length = len(text)

    while i < length:
        char = text[i]

        if char.isspace():
            i += 1
            continue

        if char.isdigit() or (char == "." and i + 1 < length and text[i + 1].isdigit()):
            value, end = _scan_number(text, i)
            tokens.append(Token("number", text[i:end], i, value))
            i = end
            continue

        if _is_name_start(char):
            start = i
            while i < length and _is_name_char(text[i]):
                i += 1
            raw = text[start:i]
            tokens.append(Token("name", raw.lower(), start))
            continue

        if text[i : i + 2] in _TWO_CHAR_OPS:
            tokens.append(Token("op", text[i : i + 2], i))
            i += 2
            continue

        if char == "!":
            tokens.append(Token("op", "!", i))
            i += 1
            continue

        if char in _ONE_CHAR_OPS:
            tokens.append(Token("op", char, i))
            i += 1
            continue

        if char == "(":
            tokens.append(Token("lparen", char, i))
            i += 1
            continue

        if char == ")":
            tokens.append(Token("rparen", char, i))
            i += 1
            continue

        if char == ",":
            tokens.append(Token("comma", char, i))
            i += 1
            continue

        if char == "=":
            raise ExpressionError(
                "Присваивание не поддерживается; для сравнения используйте '=='", i
            )

        raise ExpressionError(f"Недопустимый символ '{char}'", i)

    return tokens


def _known_names() -> list[str]:
    return sorted({*FUNCTIONS, *CONSTANTS, VARIABLE})


def _suggest(name: str) -> str | None:
    """Подбирает похожее известное имя, в том числе через похожие буквы."""
    candidates = _known_names()
    for probe in (name, name.translate(_HOMOGLYPHS).lower()):
        matches = difflib.get_close_matches(probe, candidates, n=1, cutoff=0.6)
        if matches:
            return matches[0]
    return None


# --------------------------------------------------------------------------
# Синтаксический разбор: сортировочная станция -> ОПЗ
#
# Узлы ОПЗ:
#   ('num', value)        константа или число
#   ('var',)              переменная x
#   ('bin', symbol)       бинарный оператор
#   ('neg',)              унарный минус
#   ('fact',)             постфиксный факториал
#   ('call', name, n)     вызов функции с n аргументами
# --------------------------------------------------------------------------

Node = tuple


def _stack_precedence(entry: tuple) -> int:
    if entry[0] == "unary":
        return PREC_UNARY
    return BINARY_OPS[entry[1]].precedence


def _emit(entry: tuple, output: list[Node]) -> None:
    if entry[0] == "unary":
        if entry[1] == "-":
            output.append(("neg",))
        # Унарный плюс ничего не меняет и в ОПЗ не попадает.
    else:
        output.append(("bin", entry[1]))


def _push_binary(symbol: str, ops: list, output: list[Node]) -> None:
    """Кладёт бинарный оператор, вытолкнув всё, что связывает не слабее."""
    op = BINARY_OPS[symbol]
    while ops and ops[-1][0] != "lparen":
        top = ops[-1]
        top_prec = _stack_precedence(top)
        if top_prec > op.precedence or (top_prec == op.precedence and not op.right_assoc):
            _emit(ops.pop(), output)
        else:
            break
    ops.append(("binary", symbol))


def to_rpn(tokens: Sequence[Token]) -> list[Node]:
    """Переводит поток лексем в обратную польскую запись.

    Поддерживает скобки, вызовы функций с произвольным числом аргументов,
    унарный минус, постфиксный факториал и неявное умножение (``2x``,
    ``3sin(x)``, ``2(x+1)``).

    :raises ExpressionError: при любой синтаксической ошибке.
    """
    output: list[Node] = []
    ops: list[tuple] = []
    arg_counts: list[int] = []
    expect_value = True   # ждём значение (начало, после оператора, после '(' или ',')
    after_function = False  # предыдущая лексема — имя функции, обязана идти '('
    last_was_lparen = False
    prev_kind = ""        # вид предыдущей лексемы
    last_token: Token | None = None

    def implicit_multiplication() -> None:
        """Вставляет '*' между значением и следующим за ним значением."""
        if not expect_value:
            _push_binary("*", ops, output)

    for token in tokens:
        last_token = token
        if after_function and token.kind != "lparen":
            name = ops[-1][1]
            raise ExpressionError(f"После функции '{name}' ожидается '('", token.pos)

        if token.kind == "number":
            if not expect_value and prev_kind == "number":
                # '2 3' отличается от '23' только пробелом — считать это
                # умножением слишком опасно, требуем явный оператор.
                raise ExpressionError("Пропущен оператор между числами", token.pos)
            implicit_multiplication()
            output.append(("num", token.value))
            expect_value = False
            last_was_lparen = False
            prev_kind = "number"
            continue

        if token.kind == "name":
            name = token.text
            if name in FUNCTIONS:
                implicit_multiplication()
                ops.append(("function", name, token.pos))
                after_function = True
                expect_value = True
                last_was_lparen = False
                prev_kind = "function"
                continue
            implicit_multiplication()
            if name == VARIABLE:
                output.append(("var",))
            elif name in CONSTANTS:
                output.append(("num", CONSTANTS[name]))
            else:
                hint = _suggest(name)
                message = f"Неизвестное имя '{token.text}'"
                if hint:
                    message += f"; возможно, имелось в виду '{hint}'"
                raise ExpressionError(message, token.pos)
            expect_value = False
            last_was_lparen = False
            prev_kind = "name"
            continue

        if token.kind == "lparen":
            is_call = after_function
            if not is_call:
                implicit_multiplication()
            ops.append(("lparen", is_call))
            if is_call:
                arg_counts.append(1)
            after_function = False
            expect_value = True
            last_was_lparen = True
            prev_kind = "lparen"
            continue

        if token.kind == "comma":
            if expect_value:
                raise ExpressionError("Пропущено значение перед ','", token.pos)
            while ops and ops[-1][0] != "lparen":
                _emit(ops.pop(), output)
            if not ops or not ops[-1][1]:
                raise ExpressionError("Запятая допустима только в аргументах функции", token.pos)
            arg_counts[-1] += 1
            expect_value = True
            last_was_lparen = False
            prev_kind = "comma"
            continue

        if token.kind == "rparen":
            if expect_value:
                if last_was_lparen:
                    raise ExpressionError("Пустые скобки", token.pos)
                raise ExpressionError("Пропущено значение перед ')'", token.pos)
            while ops and ops[-1][0] != "lparen":
                _emit(ops.pop(), output)
            if not ops:
                raise ExpressionError("Лишняя закрывающая скобка", token.pos)
            _, is_call = ops.pop()
            if is_call:
                _, name, name_pos = ops.pop()
                count = arg_counts.pop()
                function = FUNCTIONS[name]
                if not function.accepts(count):
                    raise ExpressionError(_arity_message(function, count), name_pos)
                output.append(("call", name, count))
            expect_value = False
            last_was_lparen = False
            prev_kind = "rparen"
            continue

        # token.kind == "op"
        symbol = token.text
        if expect_value:
            if symbol in UNARY_OPS:
                ops.append(("unary", symbol))
                last_was_lparen = False
                prev_kind = "op"
                continue
            raise ExpressionError(f"Пропущено значение перед '{symbol}'", token.pos)

        if symbol in POSTFIX_OPS:
            # Постфиксный оператор связывает крепче всего и применяется
            # к уже готовому значению, поэтому уходит в вывод сразу.
            output.append(("fact",))
            last_was_lparen = False
            prev_kind = "postfix"
            continue

        if symbol not in BINARY_OPS:
            raise ExpressionError(f"Оператор '{symbol}' не может стоять здесь", token.pos)

        _push_binary(symbol, ops, output)
        expect_value = True
        last_was_lparen = False
        prev_kind = "op"

    if after_function:
        _, name, name_pos = ops[-1]
        raise ExpressionError(f"После функции '{name}' ожидается '('", name_pos)
    if expect_value:
        end = (last_token.pos + len(last_token.text)) if last_token else None
        raise ExpressionError("Формула не закончена", end)

    while ops:
        entry = ops.pop()
        if entry[0] == "lparen":
            raise ExpressionError("Не хватает закрывающей скобки")
        if entry[0] == "function":  # pragma: no cover - невозможно: за функцией всегда '('
            raise ExpressionError(f"Функция '{entry[1]}' вызвана без аргументов", entry[2])
        _emit(entry, output)

    if not output:
        raise ExpressionError("Пустая формула")
    return output


def _arity_message(function: Function, count: int) -> str:
    if function.max_args is None:
        expected = f"не менее {function.min_args}"
    elif function.min_args == function.max_args:
        expected = f"ровно {function.min_args}"
    else:
        expected = f"от {function.min_args} до {function.max_args}"
    return (
        f"Функция '{function.name}' принимает {expected} аргументов, "
        f"а получила {count}: {function.signature}"
    )


# --------------------------------------------------------------------------
# Компиляция ОПЗ в дерево замыканий
# --------------------------------------------------------------------------


def compile_rpn(rpn: Sequence[Node]) -> Callable[[float], float]:
    """Собирает из ОПЗ функцию одного аргумента.

    Возвращаемое замыкание не разбирает текст и не смотрит в словари —
    вся диспетчеризация выполнена здесь, один раз.
    """
    stack: list[Callable[[float], float]] = []

    for node in rpn:
        kind = node[0]

        if kind == "num":
            value = node[1]
            stack.append(lambda x, _v=value: _v)

        elif kind == "var":
            stack.append(lambda x: x)

        elif kind == "neg":
            operand = _pop(stack, node)
            stack.append(lambda x, _a=operand: -_a(x))

        elif kind == "fact":
            operand = _pop(stack, node)
            stack.append(lambda x, _a=operand: _factorial(_a(x)))

        elif kind == "bin":
            right = _pop(stack, node)
            left = _pop(stack, node)
            func = BINARY_OPS[node[1]].func
            stack.append(lambda x, _f=func, _a=left, _b=right: _f(_a(x), _b(x)))

        elif kind == "call":
            name, count = node[1], node[2]
            args = [_pop(stack, node) for _ in range(count)]
            args.reverse()

            if name == "if":
                # Ветви вычисляются лениво: ln(x) в мёртвой ветви не должен
                # портить результат там, где условие его не выбирает.
                cond, on_true, on_false = args
                stack.append(
                    lambda x, _c=cond, _t=on_true, _f=on_false: _t(x) if _truthy(_c(x)) else _f(x)
                )
            else:
                func = FUNCTIONS[name].func
                if count == 1:
                    (a,) = args
                    stack.append(lambda x, _f=func, _a=a: _f(_a(x)))
                elif count == 2:
                    a, b = args
                    stack.append(lambda x, _f=func, _a=a, _b=b: _f(_a(x), _b(x)))
                else:
                    tuple_args = tuple(args)
                    stack.append(
                        lambda x, _f=func, _as=tuple_args: _f(*[g(x) for g in _as])
                    )

        else:  # pragma: no cover - защита от опечатки в самом парсере
            raise ExpressionError(f"Неизвестный узел разбора: {kind!r}")

    if len(stack) != 1:
        raise ExpressionError("Формула составлена неверно: лишние значения без оператора")
    return stack[0]


def _pop(stack: list, node: Node):
    if not stack:  # pragma: no cover - при корректном to_rpn недостижимо
        raise ExpressionError(f"Не хватает аргумента для операции {node[0]!r}")
    return stack.pop()


class Expression:
    """Разобранная и готовая к вычислению формула.

    Использование::

        expr = Expression("sin(x) / x")
        expr(1.5)   # -> 0.6650...

    Текст разбирается в конструкторе. Некорректная формула поднимает
    :class:`ExpressionError`; ошибки области определения ошибками не
    считаются и дают ``nan``.
    """

    __slots__ = ("text", "rpn", "_func")

    def __init__(self, text: str) -> None:
        self.text = text
        tokens = tokenize(text)
        if not tokens:
            raise ExpressionError("Пустая формула")
        self.rpn = to_rpn(tokens)
        self._func = compile_rpn(self.rpn)

    def __call__(self, x: float) -> float:
        """Значение функции в точке. Вне области определения возвращает ``nan``."""
        try:
            return self._func(x)
        except (ArithmeticError, ValueError):
            # Домен: log(0), asin(2), 0^-1 и подобное. TypeError сюда
            # намеренно не попадает — это была бы ошибка в самом парсере.
            return NAN

    def __repr__(self) -> str:  # pragma: no cover - отладочное представление
        return f"Expression({self.text!r})"

    @staticmethod
    def validate(text: str) -> str | None:
        """Проверяет формулу, не сохраняя её. Возвращает текст ошибки или ``None``."""
        try:
            Expression(text)
        except ExpressionError as exc:
            return str(exc)
        return None
