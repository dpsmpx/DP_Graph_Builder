"""Тесты разбора и вычисления формул.

Отдельный блок посвящён случаям, на которых ломалась прежняя реализация:
они закреплены тестами, чтобы регрессия не прошла незамеченной.
"""

from __future__ import annotations

import math

import pytest

from dp_graph.expression import (
    Expression,
    ExpressionError,
    FUNCTIONS,
    compile_rpn,
    tokenize,
)


def value(source: str, x: float = 0.0) -> float:
    return Expression(source)(x)


# --------------------------------------------------------------------------
# Регрессии: каждый случай раньше приводил к падению или пустому графику
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source, x, expected",
    [
        ("(x+1)*2", 3, 8.0),          # скобки вообще не поддерживались
        ("sin(x) + 1", 0, 1.0),       # функция перед оператором давала KeyError
        ("sin(x) * 2", 0, 0.0),
        ("-x", 3, -3.0),              # унарный минус давал IndexError
        ("-5 + x", 3, -2.0),
        ("x^-1", 4, 0.25),
        ("3! + 1", 0, 7.0),           # факториал перед оператором давал KeyError
        ("2^3^2", 0, 512.0),          # степень должна быть правоассоциативна
    ],
)
def test_previously_broken_cases(source: str, x: float, expected: float) -> None:
    assert value(source, x) == pytest.approx(expected)


def test_unknown_name_is_reported_not_silently_zero() -> None:
    # Раньше опечатка в имени молча превращалась в 0.0 из-за проверки
    # вхождения подстроки вместо проверки принадлежности.
    with pytest.raises(ExpressionError, match="Неизвестное имя"):
        Expression("abc")


def test_two_values_without_operator_is_rejected() -> None:
    with pytest.raises(ExpressionError, match="Пропущен оператор"):
        Expression("2 3")


def test_factorial_of_huge_argument_is_not_computed() -> None:
    # math.factorial(10**6) считался бы секундами на каждой точке графика.
    assert math.isnan(value("x!", 1e6))


def test_power_never_returns_complex() -> None:
    assert math.isnan(value("(0-8)^0.5"))


def test_cyrillic_homoglyph_gets_a_hint() -> None:
    with pytest.raises(ExpressionError, match="cos"):
        Expression("сos(x)")  # 'с' здесь кириллическая


# --------------------------------------------------------------------------
# Приоритеты и ассоциативность
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source, expected",
    [
        ("2+3*4", 14.0),
        ("(2+3)*4", 20.0),
        ("2*3^2", 18.0),
        ("-2^2", -4.0),        # унарный минус слабее степени
        ("(-2)^2", 4.0),
        ("2-3-4", -5.0),       # вычитание левоассоциативно
        ("2^3^2", 512.0),      # степень правоассоциативна
        ("8/4/2", 1.0),
        ("1+2<4", 1.0),        # сравнение слабее арифметики
        ("--3", 3.0),
    ],
)
def test_precedence(source: str, expected: float) -> None:
    assert value(source) == pytest.approx(expected)


# --------------------------------------------------------------------------
# Неявное умножение
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source, x, expected",
    [
        ("2x", 3, 6.0),
        ("2 x", 3, 6.0),
        ("2(x+1)", 3, 8.0),
        ("3sin(0)", 0, 0.0),
        ("x(x+1)", 3, 12.0),
        ("2pi", 0, 2 * math.pi),
        ("(x+1)(x-1)", 3, 8.0),
    ],
)
def test_implicit_multiplication(source: str, x: float, expected: float) -> None:
    assert value(source, x) == pytest.approx(expected)


def test_number_juxtaposition_is_not_multiplication() -> None:
    # '23' и '2 3' различаются одним пробелом — считать второе умножением опасно.
    assert value("23") == 23.0
    with pytest.raises(ExpressionError):
        Expression("2 3")


# --------------------------------------------------------------------------
# Функции
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source, expected",
    [
        ("log(2, 8)", 3.0),
        ("root(3, -8)", -2.0),
        ("cbrt(-27)", -3.0),
        ("max(1, 7, 3)", 7.0),
        ("min(1, 7, 3)", 1.0),
        ("clamp(9, 0, 5)", 5.0),
        ("hypot(3, 4)", 5.0),
        ("round(3.14159, 2)", 3.14),
        ("sign(-9)", -1.0),
        ("frac(-1.25)", -0.25),
        ("deg(pi)", 180.0),
        ("2.5!", math.gamma(3.5)),
    ],
)
def test_functions(source: str, expected: float) -> None:
    assert value(source) == pytest.approx(expected)


def test_case_is_ignored() -> None:
    assert value("SIN(PI)", 0) == pytest.approx(math.sin(math.pi))


def test_if_branches_are_lazy() -> None:
    # Мёртвая ветвь не вычисляется, поэтому ln(-5) не портит результат.
    assert value("if(x > 0, ln(x), 0)", -5.0) == 0.0
    assert value("if(x > 0, ln(x), 0)", math.e) == pytest.approx(1.0)


def test_nan_condition_is_false() -> None:
    assert value("if(0/0, 1, 2)") == 2.0


# --------------------------------------------------------------------------
# Область определения даёт NaN, а не исключение
# --------------------------------------------------------------------------


@pytest.mark.parametrize("source", ["1/0", "ln(0)", "ln(-1)", "sqrt(-1)", "asin(2)", "0^-1", "x%0"])
def test_domain_errors_yield_nan(source: str) -> None:
    assert math.isnan(value(source))


def test_infinities_are_filtered() -> None:
    assert math.isnan(value("exp(x)", 1e6))


# --------------------------------------------------------------------------
# Синтаксические ошибки
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source, fragment",
    [
        ("", "Пустая формула"),
        ("(x+1", "закрывающей скобки"),
        ("x+1)", "Лишняя закрывающая"),
        ("x+", "не закончена"),
        ("sin", r"ожидается '\('"),
        ("sin x", r"ожидается '\('"),
        ("sin()", "Пустые скобки"),
        ("log(2)", "принимает ровно 2"),
        ("ln(1, 2)", "принимает ровно 1"),
        ("a = 5", "Присваивание не поддерживается"),
        ("1.2.3", "больше одной точки"),
        ("x @ 2", "Недопустимый символ"),
        ("x, 2", "только в аргументах функции"),
    ],
)
def test_syntax_errors(source: str, fragment: str) -> None:
    with pytest.raises(ExpressionError, match=fragment):
        Expression(source)


def test_error_carries_position() -> None:
    with pytest.raises(ExpressionError) as info:
        Expression("1 + @")
    assert info.value.position == 4


def test_validate_returns_none_for_valid_formula() -> None:
    assert Expression.validate("sin(x)") is None
    assert Expression.validate("sin(") is not None


# --------------------------------------------------------------------------
# Свойства конвейера
# --------------------------------------------------------------------------


def test_formula_is_parsed_once() -> None:
    # Вычисление не должно возвращаться к тексту: rpn готовится в конструкторе.
    expression = Expression("2x + 1")
    assert expression.rpn == [("num", 2.0), ("var",), ("bin", "*"), ("num", 1.0), ("bin", "+")]
    assert expression(4.0) == 9.0


def test_compile_rejects_leftover_values() -> None:
    with pytest.raises(ExpressionError):
        compile_rpn([("num", 1.0), ("num", 2.0)])


def test_every_function_is_callable_with_its_minimum_arity() -> None:
    for name, function in FUNCTIONS.items():
        if name == "if":
            continue  # обрабатывается отдельно, лениво
        args = ", ".join(["1"] * function.min_args)
        result = value(f"{name}({args})")
        assert isinstance(result, float), name


def test_tokenizer_keeps_positions() -> None:
    tokens = tokenize("2 + sin(x)")
    assert [token.pos for token in tokens] == [0, 2, 4, 7, 8, 9]
