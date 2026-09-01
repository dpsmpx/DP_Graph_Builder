"""Геометрия и выборка точек графика — без привязки к тулкиту.

Модуль ничего не рисует: он переводит формулу в готовые ломаные в экранных
координатах и подбирает шаг координатной сетки. Отсутствие зависимости от
Kivy позволяет покрыть всю нетривиальную математику обычными тестами.

Ключевые решения:

* Единый масштаб по обеим осям (``units_per_pixel``). Окружность выглядит
  окружностью, а наклон прямой соответствует её коэффициенту.
* Разрывы. Точки, где функция не определена, и переходы через полюс
  (``1/x`` в нуле) рвут ломаную, вместо того чтобы соединяться отвесной
  линией через весь экран.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

__all__ = ["View", "build_polylines", "nice_step", "format_tick", "grid_lines"]

# Насколько далеко за пределы окна разрешено уводить точку, прежде чем её
# координата будет прижата к границе. Небольшой запас сохраняет правильный
# наклон линии, уходящей за край.
CLIP_SCREENS = 1.5

# Целевое расстояние между линиями сетки в пикселях.
TARGET_GRID_PX = 90.0


@dataclass
class View:
    """Прямоугольник данных, отображаемый в прямоугольник экрана.

    :param cx: координата x данных в центре окна.
    :param cy: координата y данных в центре окна.
    :param units_per_pixel: сколько единиц данных приходится на пиксель.
    :param left, bottom: левый нижний угол области рисования в координатах окна.
    :param width, height: размеры области рисования в пикселях.
    """

    cx: float = 0.0
    cy: float = 0.0
    units_per_pixel: float = 0.02
    left: float = 0.0
    bottom: float = 0.0
    width: float = 100.0
    height: float = 100.0

    # -- границы -----------------------------------------------------------

    @property
    def x_min(self) -> float:
        return self.cx - self.width * 0.5 * self.units_per_pixel

    @property
    def x_max(self) -> float:
        return self.cx + self.width * 0.5 * self.units_per_pixel

    @property
    def y_min(self) -> float:
        return self.cy - self.height * 0.5 * self.units_per_pixel

    @property
    def y_max(self) -> float:
        return self.cy + self.height * 0.5 * self.units_per_pixel

    # -- преобразования координат -----------------------------------------

    def to_screen_x(self, x: float) -> float:
        return self.left + self.width * 0.5 + (x - self.cx) / self.units_per_pixel

    def to_screen_y(self, y: float) -> float:
        return self.bottom + self.height * 0.5 + (y - self.cy) / self.units_per_pixel

    def to_data_x(self, sx: float) -> float:
        return self.cx + (sx - self.left - self.width * 0.5) * self.units_per_pixel

    def to_data_y(self, sy: float) -> float:
        return self.cy + (sy - self.bottom - self.height * 0.5) * self.units_per_pixel

    # -- операции жестов ---------------------------------------------------

    def pan_pixels(self, dx: float, dy: float) -> None:
        """Сдвигает окно так, будто холст потащили пальцем на (dx, dy)."""
        self.cx -= dx * self.units_per_pixel
        self.cy -= dy * self.units_per_pixel

    def zoom_at(self, factor: float, sx: float, sy: float) -> None:
        """Меняет масштаб, оставляя точку экрана (sx, sy) на месте.

        :param factor: >1 — приблизить, <1 — отдалить.
        """
        if factor <= 0 or not math.isfinite(factor):
            return
        anchor_x = self.to_data_x(sx)
        anchor_y = self.to_data_y(sy)
        new_upp = _clamp_scale(self.units_per_pixel / factor)
        if new_upp == self.units_per_pixel:
            return
        self.units_per_pixel = new_upp
        # Возвращаем якорь на прежнее место экрана.
        self.cx = anchor_x - (sx - self.left - self.width * 0.5) * new_upp
        self.cy = anchor_y - (sy - self.bottom - self.height * 0.5) * new_upp


# Пределы масштаба. Снизу — чтобы разность соседних координат не утонула
# в точности float, сверху — чтобы окно не уезжало в бессмысленные величины.
MIN_UNITS_PER_PIXEL = 1e-9
MAX_UNITS_PER_PIXEL = 1e9


def _clamp_scale(value: float) -> float:
    if not math.isfinite(value):
        return MIN_UNITS_PER_PIXEL
    return min(max(value, MIN_UNITS_PER_PIXEL), MAX_UNITS_PER_PIXEL)


def build_polylines(
    func: Callable[[float], float],
    view: View,
    samples: int | None = None,
) -> list[list[float]]:
    """Считает график и возвращает список ломаных в экранных координатах.

    Каждая ломаная — плоский список ``[x1, y1, x2, y2, ...]``, готовый для
    передачи в примитив линии. Разрыв области определения или переход через
    полюс начинают новую ломаную.

    :param samples: число точек; по умолчанию — по одной на пиксель ширины.
    """
    if view.width <= 0 or view.height <= 0:
        return []

    if samples is None:
        samples = int(view.width)
    samples = max(2, min(int(samples), 4000))

    x_min = view.x_min
    step = (view.x_max - x_min) / (samples - 1)

    # Скачок, который считаем полюсом, а не участком кривой: значения по обе
    # стороны разошлись больше чем на высоту окна и имеют разные знаки.
    pole_gap = (view.y_max - view.y_min)
    clip_low = view.bottom - view.height * CLIP_SCREENS
    clip_high = view.bottom + view.height * (1.0 + CLIP_SCREENS)

    polylines: list[list[float]] = []
    current: list[float] = []
    prev_y: float | None = None

    for i in range(samples):
        x = x_min + i * step
        y = func(x)

        if y != y or y in (math.inf, -math.inf):  # NaN или бесконечность
            if len(current) >= 4:
                polylines.append(current)
            current = []
            prev_y = None
            continue

        if prev_y is not None and _is_pole(prev_y, y, pole_gap):
            if len(current) >= 4:
                polylines.append(current)
            current = []

        sx = view.to_screen_x(x)
        sy = view.to_screen_y(y)
        current.append(sx)
        current.append(min(max(sy, clip_low), clip_high))
        prev_y = y

    if len(current) >= 4:
        polylines.append(current)
    return polylines


def _is_pole(prev_y: float, y: float, pole_gap: float) -> bool:
    """Признак вертикальной асимптоты между двумя соседними точками."""
    if prev_y * y >= 0:
        return False
    return abs(prev_y) > pole_gap and abs(y) > pole_gap


def nice_step(units_per_pixel: float, target_px: float = TARGET_GRID_PX) -> float:
    """Подбирает «круглый» шаг сетки (1, 2 или 5 на десятичный порядок)."""
    raw = units_per_pixel * target_px
    if raw <= 0 or not math.isfinite(raw):
        return 1.0
    exponent = math.floor(math.log10(raw))
    magnitude = 10.0 ** exponent
    for multiple in (1.0, 2.0, 5.0):
        if raw <= multiple * magnitude:
            return multiple * magnitude
    return 10.0 * magnitude


def grid_lines(low: float, high: float, step: float) -> list[float]:
    """Координаты линий сетки, попадающие в диапазон [low, high]."""
    if step <= 0 or not math.isfinite(step):
        return []
    count = int((high - low) / step) + 2
    if count > 400:  # защита от вырожденного масштаба
        return []
    start = math.floor(low / step) * step
    values = []
    for i in range(count + 1):
        value = start + i * step
        if low - step * 0.5 <= value <= high + step * 0.5:
            values.append(value)
    return values


def format_tick(value: float, step: float) -> str:
    """Подпись деления с числом знаков, соответствующим шагу сетки."""
    if abs(value) < step * 1e-6:
        return "0"
    if step >= 1e6 or step < 1e-4:
        return f"{value:.0e}".replace("e-0", "e-").replace("e+0", "e")
    # Число знаков берём из самого шага, а не из его порядка: у шага 0.25
    # порядок равен -1, но одного знака после запятой ему не хватает.
    digits = 0
    while digits < 12 and abs(round(step, digits) - step) > abs(step) * 1e-9:
        digits += 1
    text = f"{value:.{digits}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"
