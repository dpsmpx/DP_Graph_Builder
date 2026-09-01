"""Тесты интерфейса: экраны, список формул, жесты.

Запускаются только при доступном окне Kivy: ``xvfb-run -a python -m pytest``.
"""

from __future__ import annotations

import os
import sys

import pytest



def _window_available() -> bool:
    """Есть ли графический вывод.

    Проверка окружения идёт ДО импорта Kivy сознательно: провайдер окна X11
    при отсутствии дисплея завершает процесс средствами C, и никакой
    try/except на уровне Python его не остановит — падал бы весь прогон,
    а не только тесты интерфейса.
    """
    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        return False
    try:
        from kivy.core.window import Window
    except BaseException:
        return False
    return Window is not None


pytestmark = pytest.mark.skipif(
    not _window_available(),
    reason="нужен графический вывод (например, xvfb-run)",
)


@pytest.fixture
def app(tmp_path):
    from dp_graph.app import DPGraphBuilderApp

    instance = DPGraphBuilderApp(storage_path=tmp_path / "formulas.json")
    instance.build()
    # Виджеты вне текущего экрана размера не получают — задаём явно.
    instance.graph_screen.graph.size = (420, 780)
    instance.graph_screen.graph.pos = (0, 0)
    return instance


class Touch:
    """Суррогат касания Kivy: нужен только интерфейс, который читает виджет."""

    def __init__(self, x: float, y: float) -> None:
        self.x, self.y = float(x), float(y)
        self.dx = self.dy = 0.0
        self.grab_current = None
        self.is_mouse_scrolling = False
        self.button = None

    @property
    def pos(self):
        return (self.x, self.y)

    def grab(self, widget):
        self.grab_current = widget

    def ungrab(self, widget):
        self.grab_current = None

    def move(self, x: float, y: float) -> None:
        self.dx, self.dy = x - self.x, y - self.y
        self.x, self.y = float(x), float(y)


# --------------------------------------------------------------------------
# Меню и список формул
# --------------------------------------------------------------------------


def test_last_used_formula_is_in_the_input(tmp_path) -> None:
    from dp_graph.app import DPGraphBuilderApp

    first = DPGraphBuilderApp(storage_path=tmp_path / "formulas.json")
    first.build()
    first.open_graph("cos(2x)")

    second = DPGraphBuilderApp(storage_path=tmp_path / "formulas.json")
    second.build()
    assert second.menu_screen.input.text == "cos(2x)"


def test_building_a_graph_adds_the_formula_to_the_list(app) -> None:
    app.open_graph("x^3 - x")
    assert app.store.formulas[0] == "x^3 - x"
    assert app.manager.current == "graph"


def test_invalid_formula_reports_and_stays_in_menu(app) -> None:
    app.open_graph("sin(")
    assert app.manager.current == "menu"
    assert app.menu_screen.status.text  # причина показана пользователю
    assert "sin(" not in app.store.formulas


def test_unclosed_bracket_is_named_in_the_message(app) -> None:
    app.open_graph("sin(x")
    assert "скобк" in app.menu_screen.status.text.lower()
    assert app.manager.current == "menu"


def test_blank_formula_is_refused(app) -> None:
    app.open_graph("   ")
    assert app.manager.current == "menu"
    assert app.menu_screen.status.text


def test_row_count_matches_the_store(app) -> None:
    app.menu_screen.refresh()
    from dp_graph.app import FormulaRow

    rows = [w for w in app.menu_screen.list_layout.children if isinstance(w, FormulaRow)]
    assert len(rows) == len(app.store.formulas)


def test_tapping_a_row_loads_it_into_the_input(app) -> None:
    from dp_graph.app import FormulaRow

    app.menu_screen.refresh()
    row = [w for w in app.menu_screen.list_layout.children if isinstance(w, FormulaRow)][0]
    row.pick_button.dispatch("on_release")
    assert app.menu_screen.input.text in app.store.formulas


def test_delete_button_removes_the_row(app) -> None:
    from dp_graph.app import FormulaRow

    app.menu_screen.refresh()
    rows = [w for w in app.menu_screen.list_layout.children if isinstance(w, FormulaRow)]
    victim = rows[0].pick_button.text
    before = len(app.store.formulas)
    rows[0].delete_button.dispatch("on_release")
    assert victim not in app.store.formulas
    assert len(app.store.formulas) == before - 1


def test_typing_reports_errors_live(app) -> None:
    app.menu_screen.input.text = "sin("
    assert app.menu_screen.status.text
    app.menu_screen.input.text = "sin(x)"
    assert app.menu_screen.status.text == ""


# --------------------------------------------------------------------------
# Навигация
# --------------------------------------------------------------------------


def test_help_and_back(app) -> None:
    app.show_help()
    assert app.manager.current == "help"
    app.show_menu()
    assert app.manager.current == "menu"


def test_hardware_back_button_returns_to_menu(app) -> None:
    app.show_help()
    assert app._on_keyboard(None, 27) is True
    assert app.manager.current == "menu"
    # В самом меню кнопка «назад» отдаётся системе — она закрывает приложение.
    assert app._on_keyboard(None, 27) is False


# --------------------------------------------------------------------------
# Жесты на графике
# --------------------------------------------------------------------------


def test_one_finger_drag_pans(app) -> None:
    app.open_graph("sin(x)")
    graph = app.graph_screen.graph
    before = graph.view.cx
    touch = Touch(200, 400)
    graph.on_touch_down(touch)
    touch.move(120, 400)
    graph.on_touch_move(touch)
    graph.on_touch_up(touch)
    assert graph.view.cx > before  # палец влево -> окно вправо


def test_two_finger_spread_zooms_in(app) -> None:
    app.open_graph("sin(x)")
    graph = app.graph_screen.graph
    before = graph.view.units_per_pixel
    first, second = Touch(160, 400), Touch(260, 400)
    graph.on_touch_down(first)
    graph.on_touch_down(second)
    first.move(100, 400)
    graph.on_touch_move(first)
    second.move(320, 400)
    graph.on_touch_move(second)
    graph.on_touch_up(first)
    graph.on_touch_up(second)
    assert graph.view.units_per_pixel < before


def test_pinch_keeps_the_midpoint_anchored(app) -> None:
    app.open_graph("sin(x)")
    graph = app.graph_screen.graph
    first, second = Touch(160, 400), Touch(260, 400)
    graph.on_touch_down(first)
    graph.on_touch_down(second)
    graph.on_touch_move(first)  # зафиксировать опорные значения
    anchor_before = graph.view.to_data_x(210)
    first.move(140, 400)
    second.move(280, 400)
    graph.on_touch_move(first)
    graph.on_touch_move(second)
    assert graph.view.to_data_x(210) == pytest.approx(anchor_before, abs=1e-6)


def test_reset_restores_position_and_scale(app) -> None:
    app.open_graph("sin(x)")
    graph = app.graph_screen.graph
    original = (graph.view.cx, graph.view.cy, graph.view.units_per_pixel)
    touch = Touch(200, 400)
    graph.on_touch_down(touch)
    touch.move(50, 250)
    graph.on_touch_move(touch)
    graph.on_touch_up(touch)
    graph.view.zoom_at(3.0, 200, 400)
    assert (graph.view.cx, graph.view.cy) != original[:2]

    graph.reset_view()
    assert (graph.view.cx, graph.view.cy, graph.view.units_per_pixel) == original


def test_touch_outside_the_widget_is_ignored(app) -> None:
    app.open_graph("sin(x)")
    graph = app.graph_screen.graph
    assert graph.on_touch_down(Touch(-50, -50)) is False


def test_untouched_view_refits_on_resize(app) -> None:
    app.open_graph("sin(x)")
    graph = app.graph_screen.graph
    graph.size = (780, 420)  # поворот экрана
    assert graph.view.units_per_pixel == pytest.approx(16.0 / 420)


def test_adjusted_view_survives_resize(app) -> None:
    app.open_graph("sin(x)")
    graph = app.graph_screen.graph
    touch = Touch(200, 400)
    graph.on_touch_down(touch)
    touch.move(100, 400)
    graph.on_touch_move(touch)
    graph.on_touch_up(touch)
    moved = graph.view.cx
    graph.size = (780, 420)
    assert graph.view.cx == pytest.approx(moved)


def test_switching_formula_resets_the_view(app) -> None:
    app.open_graph("sin(x)")
    graph = app.graph_screen.graph
    graph.view.cx = 99.0
    app.show_menu()
    app.open_graph("cos(x)")
    assert graph.view.cx == 0.0


def test_graph_screen_survives_a_broken_formula(app) -> None:
    # Прямой вызов в обход проверки не должен ронять экран.
    app.graph_screen.show("sin(")
    assert app.graph_screen.graph.expression is None


def test_drawing_produces_canvas_instructions(app) -> None:
    app.open_graph("sin(x)")
    graph = app.graph_screen.graph
    graph._redraw()
    assert len(graph.canvas.children) > 10
