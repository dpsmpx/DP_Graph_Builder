"""Тесты геометрии окна просмотра и выборки точек графика."""

from __future__ import annotations

import math

import pytest

from dp_graph.expression import Expression
from dp_graph.plotting import (
    MAX_UNITS_PER_PIXEL,
    MIN_UNITS_PER_PIXEL,
    View,
    build_polylines,
    format_tick,
    grid_lines,
    nice_step,
)


@pytest.fixture
def view() -> View:
    return View(cx=0.0, cy=0.0, units_per_pixel=0.02, left=0.0, bottom=0.0, width=500.0, height=400.0)


# --------------------------------------------------------------------------
# Преобразования координат
# --------------------------------------------------------------------------


def test_bounds(view: View) -> None:
    assert view.x_min == pytest.approx(-5.0)
    assert view.x_max == pytest.approx(5.0)
    assert view.y_min == pytest.approx(-4.0)
    assert view.y_max == pytest.approx(4.0)


def test_screen_and_data_are_inverse(view: View) -> None:
    for value in (-4.0, -0.5, 0.0, 1.25, 3.0):
        assert view.to_data_x(view.to_screen_x(value)) == pytest.approx(value)
        assert view.to_data_y(view.to_screen_y(value)) == pytest.approx(value)


def test_axes_share_one_scale(view: View) -> None:
    # Единица длины по x и по y должна занимать одинаковое число пикселей,
    # иначе окружность выглядит эллипсом, а наклон прямой врёт.
    pixels_x = view.to_screen_x(1.0) - view.to_screen_x(0.0)
    pixels_y = view.to_screen_y(1.0) - view.to_screen_y(0.0)
    assert pixels_x == pytest.approx(pixels_y)


# --------------------------------------------------------------------------
# Жесты
# --------------------------------------------------------------------------


def test_pan_moves_opposite_to_finger(view: View) -> None:
    view.pan_pixels(50.0, 0.0)  # палец тянет вправо -> окно уезжает влево
    assert view.cx == pytest.approx(-1.0)


def test_zoom_keeps_the_anchor_point_still(view: View) -> None:
    anchor = (120.0, 310.0)
    before = (view.to_data_x(anchor[0]), view.to_data_y(anchor[1]))
    view.zoom_at(2.5, *anchor)
    after = (view.to_data_x(anchor[0]), view.to_data_y(anchor[1]))
    assert after[0] == pytest.approx(before[0])
    assert after[1] == pytest.approx(before[1])


def test_zoom_in_reduces_units_per_pixel(view: View) -> None:
    view.zoom_at(2.0, 250.0, 200.0)
    assert view.units_per_pixel == pytest.approx(0.01)


def test_zoom_is_bounded(view: View) -> None:
    for _ in range(200):
        view.zoom_at(10.0, 250.0, 200.0)
    assert view.units_per_pixel >= MIN_UNITS_PER_PIXEL
    for _ in range(400):
        view.zoom_at(0.1, 250.0, 200.0)
    assert view.units_per_pixel <= MAX_UNITS_PER_PIXEL


@pytest.mark.parametrize("factor", [0.0, -1.0, float("nan"), float("inf")])
def test_degenerate_zoom_is_ignored(view: View, factor: float) -> None:
    before = view.units_per_pixel
    view.zoom_at(factor, 250.0, 200.0)
    assert view.units_per_pixel == before


# --------------------------------------------------------------------------
# Выборка точек
# --------------------------------------------------------------------------


def test_continuous_function_is_one_polyline(view: View) -> None:
    assert len(build_polylines(Expression("sin(x)"), view)) == 1


def test_pole_breaks_the_line(view: View) -> None:
    # 1/x не должен соединяться отвесной чертой через весь экран.
    polylines = build_polylines(Expression("1/x"), view)
    assert len(polylines) == 2


def test_undefined_region_is_skipped(view: View) -> None:
    polylines = build_polylines(Expression("sqrt(x)"), view)
    assert len(polylines) == 1
    xs = polylines[0][0::2]
    assert min(view.to_data_x(x) for x in xs) >= -1e-9


def test_points_stay_near_the_widget(view: View) -> None:
    # Огромные значения прижимаются к полосе вокруг виджета: координаты
    # в миллионы пикселей рисуются непредсказуемо.
    for polyline in build_polylines(Expression("x^9"), view):
        for y in polyline[1::2]:
            assert -2000.0 < y < 2000.0


def test_empty_widget_produces_nothing() -> None:
    assert build_polylines(Expression("x"), View(width=0.0, height=0.0)) == []


def test_sample_count_is_capped(view: View) -> None:
    polylines = build_polylines(Expression("x"), view, samples=10**9)
    assert sum(len(p) // 2 for p in polylines) <= 4000


# --------------------------------------------------------------------------
# Сетка и подписи
# --------------------------------------------------------------------------


@pytest.mark.parametrize("units_per_pixel", [1e-6, 1e-3, 0.02, 0.5, 7.0, 1e4])
def test_nice_step_is_a_round_number(units_per_pixel: float) -> None:
    step = nice_step(units_per_pixel)
    mantissa = step / 10.0 ** math.floor(math.log10(step))
    assert round(mantissa, 6) in (1.0, 2.0, 5.0)


@pytest.mark.parametrize("units_per_pixel", [1e-6, 1e-3, 0.02, 0.5, 7.0])
def test_grid_spacing_stays_readable(units_per_pixel: float) -> None:
    # Шаг сетки должен держаться в разумных пределах на любом масштабе.
    pixels = nice_step(units_per_pixel) / units_per_pixel
    assert 30.0 <= pixels <= 250.0


def test_grid_lines_cover_the_range() -> None:
    values = grid_lines(-5.0, 5.0, 2.0)
    assert values[0] <= -5.0 and values[-1] >= 5.0


def test_grid_lines_refuse_degenerate_steps() -> None:
    assert grid_lines(-5.0, 5.0, 0.0) == []
    assert grid_lines(-1e9, 1e9, 1.0) == []


@pytest.mark.parametrize(
    "value, step, expected",
    [(0.0, 1.0, "0"), (2.0, 1.0, "2"), (-3.0, 1.0, "-3"), (0.25, 0.25, "0.25"), (1.5, 0.5, "1.5")],
)
def test_format_tick(value: float, step: float, expected: str) -> None:
    assert format_tick(value, step) == expected
