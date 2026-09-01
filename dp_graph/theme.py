"""Палитра и метрики интерфейса.

Цвета взяты из проверенной палитры для светлой подложки: линия графика
#2a78d6 проходит проверки контраста (>= 3:1) и насыщенности относительно
поверхности #fcfcfb. Сетка и оси намеренно приглушены — они не должны
спорить с кривой, ради которой всё и рисуется.
"""

from __future__ import annotations

__all__ = ["rgba", "SURFACE", "CARD", "INK", "INK_MUTED", "ACCENT", "ACCENT_INK",
           "DANGER", "GRID_MINOR", "GRID_MAJOR", "AXIS", "CURVE", "BORDER", "FIELD"]


def rgba(value: str, alpha: float = 1.0) -> tuple[float, float, float, float]:
    """Переводит '#rrggbb' в кортеж Kivy (r, g, b, a) в долях единицы."""
    value = value.lstrip("#")
    red, green, blue = (int(value[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    return (red, green, blue, alpha)


SURFACE = rgba("#f4f4f2")      # фон экрана
CARD = rgba("#fcfcfb")         # подложка графика и карточек
FIELD = rgba("#ffffff")        # поле ввода
BORDER = rgba("#e2e2de")       # разделители

INK = rgba("#0b0b0b")          # основной текст
INK_MUTED = rgba("#52514e")    # подписи делений, пояснения

ACCENT = rgba("#2a78d6")       # активные кнопки
ACCENT_INK = rgba("#ffffff")   # текст на активной кнопке
DANGER = rgba("#e34948")       # удаление

CURVE = rgba("#2a78d6")        # линия графика
AXIS = rgba("#52514e")         # оси координат
GRID_MAJOR = rgba("#d9d9d4")   # основная сетка
GRID_MINOR = rgba("#ebebe7")   # вспомогательная сетка
