"""Виджет координатной плоскости с жестовым управлением.

Что умеет:

* перетаскивание одним пальцем — сдвиг осей;
* сведение и разведение двух пальцев — масштаб вокруг середины между ними;
* колесо мыши — тот же масштаб на настольной машине;
* :meth:`GraphView.reset_view` — возврат к исходному положению и масштабу.

Перерисовка идёт не чаще одного раза за кадр: события касаний приходят
пачками, и без объединения каждый кадр пересчитывался бы несколько раз.
"""

from __future__ import annotations

import math

from kivy.clock import Clock
from kivy.core.text import Label as CoreLabel
from kivy.graphics import Color, Line, Rectangle
from kivy.metrics import dp, sp
from kivy.uix.widget import Widget

from . import theme
from .expression import Expression
from .plotting import View, build_polylines, format_tick, grid_lines, nice_step

__all__ = ["GraphView"]

# Сколько единиц данных укладывается по ВЫСОТЕ при сбросе масштаба.
# Масштаб по осям одинаковый (иначе наклоны и окружности врут), поэтому
# ширина получается из высоты сама. Привязка именно к высоте выбрана из-за
# вертикального экрана телефона: посадка по ширине растянула бы диапазон y
# почти вдвое и прижала бы любую кривую к оси.
DEFAULT_SPAN = 16.0

# Вспомогательная сетка рисуется, только когда её линии не сливаются.
MIN_MINOR_GAP_DP = 11.0

# Ниже этого расстояния между пальцами (в пикселях) щипок не считаем:
# два касания почти в одной точке дают взрывной коэффициент масштаба.
MIN_PINCH_DISTANCE = 20.0


class GraphView(Widget):
    """Рисует график выражения и обрабатывает жесты."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.view = View()
        self._expression: Expression | None = None
        self._error: str | None = None
        self._touches: list = []
        self._pinch_distance: float | None = None
        self._pinch_midpoint: tuple[float, float] | None = None
        # Пока пользователь не двигал график сам, вид пересчитывается под
        # каждый новый размер виджета. Это чинит две вещи разом: первый
        # осмысленный размер приходит уже после создания виджета (до него
        # ширина равна заглушке), и поворот экрана не должен оставлять
        # нетронутый график в масштабе от прежней ориентации.
        self._user_adjusted = False
        # create_trigger склеивает несколько запросов в одну перерисовку за кадр.
        self._redraw_trigger = Clock.create_trigger(self._redraw, 0)
        self.bind(pos=self._on_geometry, size=self._on_geometry)

    # -- внешний интерфейс -------------------------------------------------

    @property
    def expression(self) -> Expression | None:
        return self._expression

    def set_expression(self, expression: Expression | None, error: str | None = None) -> None:
        """Задаёт отображаемую формулу (или сообщение об ошибке вместо неё)."""
        self._expression = expression
        self._error = error
        self._redraw_trigger()

    def reset_view(self) -> None:
        """Возвращает начальные положение и масштаб."""
        self.view.cx = 0.0
        self.view.cy = 0.0
        self.view.units_per_pixel = DEFAULT_SPAN / max(1.0, self.height)
        self._user_adjusted = False
        self._redraw_trigger()

    # -- геометрия ---------------------------------------------------------

    def _on_geometry(self, *_args) -> None:
        self.view.left = self.x
        self.view.bottom = self.y
        self.view.width = self.width
        self.view.height = self.height
        if not self._user_adjusted and self.width > 1 and self.height > 1:
            self.reset_view()
            return
        self._redraw_trigger()

    # -- жесты -------------------------------------------------------------

    def on_touch_down(self, touch) -> bool:
        if not self.collide_point(*touch.pos):
            return False

        if getattr(touch, "is_mouse_scrolling", False):
            factor = 1.2 if touch.button == "scrollup" else 1.0 / 1.2
            self.view.zoom_at(factor, touch.x, touch.y)
            self._user_adjusted = True
            self._redraw_trigger()
            return True

        touch.grab(self)
        self._touches.append(touch)
        self._reset_pinch()
        return True

    def on_touch_move(self, touch) -> bool:
        if touch.grab_current is not self:
            return False

        if len(self._touches) == 1:
            self.view.pan_pixels(touch.dx, touch.dy)
        elif len(self._touches) >= 2:
            self._handle_pinch(self._touches[0], self._touches[1])

        self._user_adjusted = True
        self._redraw_trigger()
        return True

    def on_touch_up(self, touch) -> bool:
        if touch.grab_current is not self:
            return False
        touch.ungrab(self)
        if touch in self._touches:
            self._touches.remove(touch)
        # Оставшийся палец не должен «прыгнуть»: сбрасываем опорные значения.
        self._reset_pinch()
        return True

    def _reset_pinch(self) -> None:
        self._pinch_distance = None
        self._pinch_midpoint = None

    def _handle_pinch(self, first, second) -> None:
        distance = math.dist(first.pos, second.pos)
        midpoint = (
            (first.x + second.x) * 0.5,
            (first.y + second.y) * 0.5,
        )

        if self._pinch_distance is not None and self._pinch_midpoint is not None:
            # Сдвиг середины между пальцами тащит картинку...
            self.view.pan_pixels(
                midpoint[0] - self._pinch_midpoint[0],
                midpoint[1] - self._pinch_midpoint[1],
            )
            # ...а изменение расстояния между ними меняет масштаб вокруг неё.
            if distance > MIN_PINCH_DISTANCE and self._pinch_distance > MIN_PINCH_DISTANCE:
                self.view.zoom_at(distance / self._pinch_distance, midpoint[0], midpoint[1])

        self._pinch_distance = distance
        self._pinch_midpoint = midpoint

    # -- рисование ---------------------------------------------------------

    def _redraw(self, *_args) -> None:
        self.canvas.clear()
        if self.width <= 1 or self.height <= 1:
            return

        view = self.view
        with self.canvas:
            Color(*theme.CARD)
            Rectangle(pos=self.pos, size=self.size)

            step = nice_step(view.units_per_pixel)
            self._draw_grid(view, step)
            self._draw_axes(view)
            self._draw_curve(view)

        # Подписи рисуем последними, поверх кривой, чтобы они читались.
        self._draw_tick_labels(view, step)
        if self._error:
            self._draw_message(self._error)

    def _draw_grid(self, view: View, step: float) -> None:
        minor = step / 5.0
        if minor / view.units_per_pixel >= dp(MIN_MINOR_GAP_DP):
            Color(*theme.GRID_MINOR)
            for value in grid_lines(view.x_min, view.x_max, minor):
                sx = round(view.to_screen_x(value)) + 0.5
                Line(points=[sx, self.y, sx, self.top], width=0.5)
            for value in grid_lines(view.y_min, view.y_max, minor):
                sy = round(view.to_screen_y(value)) + 0.5
                Line(points=[self.x, sy, self.right, sy], width=0.5)

        Color(*theme.GRID_MAJOR)
        for value in grid_lines(view.x_min, view.x_max, step):
            sx = round(view.to_screen_x(value)) + 0.5
            Line(points=[sx, self.y, sx, self.top], width=0.5)
        for value in grid_lines(view.y_min, view.y_max, step):
            sy = round(view.to_screen_y(value)) + 0.5
            Line(points=[self.x, sy, self.right, sy], width=0.5)

    def _draw_axes(self, view: View) -> None:
        Color(*theme.AXIS)
        if view.y_min <= 0.0 <= view.y_max:
            sy = round(view.to_screen_y(0.0)) + 0.5
            Line(points=[self.x, sy, self.right, sy], width=0.9)
        if view.x_min <= 0.0 <= view.x_max:
            sx = round(view.to_screen_x(0.0)) + 0.5
            Line(points=[sx, self.y, sx, self.top], width=0.9)

    def _draw_curve(self, view: View) -> None:
        if self._expression is None:
            return
        Color(*theme.CURVE)
        for polyline in build_polylines(self._expression, view):
            Line(points=polyline, width=dp(0.9), cap="round", joint="round")

    def _draw_tick_labels(self, view: View, step: float) -> None:
        """Подписи делений вдоль осей, прижатые к краю, если ось ушла за экран."""
        padding = dp(3)
        # Ось X подписываем под горизонтальной осью, но не выпуская за виджет.
        axis_y = view.to_screen_y(0.0)
        below_axis = min(max(axis_y - dp(16), self.y + padding), self.top - dp(16))
        for value in grid_lines(view.x_min, view.x_max, step):
            if abs(value) < step * 1e-6:
                continue
            self._blit_label(
                format_tick(value, step),
                view.to_screen_x(value) + padding,
                below_axis,
            )

        axis_x = view.to_screen_x(0.0)
        left_of_axis = min(max(axis_x + padding, self.x + padding), self.right - dp(40))
        for value in grid_lines(view.y_min, view.y_max, step):
            if abs(value) < step * 1e-6:
                continue
            self._blit_label(
                format_tick(value, step),
                left_of_axis,
                view.to_screen_y(value) + padding,
            )

        # Начало координат подписываем один раз, если оно видно.
        if view.x_min <= 0 <= view.x_max and view.y_min <= 0 <= view.y_max:
            self._blit_label("0", axis_x + padding, axis_y - dp(16))

    def _blit_label(self, text: str, x: float, y: float) -> None:
        label = CoreLabel(text=text, font_size=sp(11), color=theme.INK_MUTED)
        label.refresh()
        texture = label.texture
        # Подпись, вылезающую за край виджета, лучше не рисовать вовсе:
        # обрезанное число читается хуже, чем его отсутствие.
        if (
            x < self.x
            or y < self.y
            or x + texture.width > self.right
            or y + texture.height > self.top
        ):
            return
        with self.canvas:
            Color(1, 1, 1, 1)  # текстура уже несёт свой цвет, тонировать не нужно
            Rectangle(texture=texture, pos=(round(x), round(y)), size=texture.size)

    def _draw_message(self, text: str) -> None:
        label = CoreLabel(text=text, font_size=sp(13), color=theme.DANGER)
        label.refresh()
        texture = label.texture
        with self.canvas:
            Color(1, 1, 1, 1)
            Rectangle(
                texture=texture,
                pos=(self.center_x - texture.width / 2, self.center_y - texture.height / 2),
                size=texture.size,
            )
