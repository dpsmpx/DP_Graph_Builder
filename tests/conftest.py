"""Общая настройка тестов.

Переменные окружения выставляются до импорта Kivy: иначе он попытается
разобрать аргументы pytest как свои и засорит вывод логом.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIVY_NO_ARGS", "1")
os.environ.setdefault("KIVY_NO_CONSOLELOG", "1")
