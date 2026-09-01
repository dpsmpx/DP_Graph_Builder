"""Хранение списка формул на диске.

Формат — один JSON-файл::

    {"version": 1, "current": "sin(x)", "formulas": ["sin(x)", "x^2"]}

Запись атомарная (во временный файл рядом, затем ``os.replace``), поэтому
выключение устройства посреди сохранения не оставит обрезанный файл.
Битый или чужой файл не роняет приложение: список просто откатывается к
набору по умолчанию.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

__all__ = ["FormulaStore", "DEFAULT_FORMULAS", "MAX_FORMULAS", "MAX_LENGTH"]

SCHEMA_VERSION = 1

# Потолок на размер списка и длину формулы: файл настроек не должен расти
# неограниченно, а формула в мегабайт всё равно неразбираема.
MAX_FORMULAS = 200
MAX_LENGTH = 500

DEFAULT_FORMULAS: tuple[str, ...] = (
    "sin(x)",
    "x^2",
    "1/x",
    "sin(x)/x",
    "sqrt(abs(x))",
    "2sin(x) + cos(3x)",
    "if(x > 0, ln(x), -ln(-x))",
    "x - floor(x)",
)


class FormulaStore:
    """Список сохранённых формул и последняя использованная.

    Список упорядочен от самой свежей к самой старой: добавление уже
    существующей формулы просто поднимает её наверх, а не плодит дубликаты.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self.formulas: list[str] = []
        self.current: str = ""
        self.load()

    # -- ввод/вывод --------------------------------------------------------

    def load(self) -> None:
        """Читает файл. При любой проблеме подставляет значения по умолчанию."""
        data = None
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            pass
        except (OSError, ValueError, UnicodeDecodeError):
            # Файл повреждён или недоступен — молча начинаем с чистого листа,
            # терять работоспособность приложения из-за настроек нельзя.
            pass

        formulas: list[str] = []
        current = ""
        if isinstance(data, dict):
            raw_list = data.get("formulas")
            if isinstance(raw_list, list):
                formulas = [_clean(item) for item in raw_list if _clean(item)]
            current = _clean(data.get("current"))

        if not formulas:
            formulas = list(DEFAULT_FORMULAS)
        if not current:
            current = formulas[0]

        self.formulas = _dedupe(formulas)[:MAX_FORMULAS]
        self.current = current

    def save(self) -> bool:
        """Атомарно записывает файл. Возвращает ``False``, если не удалось."""
        payload = {
            "version": SCHEMA_VERSION,
            "current": self.current,
            "formulas": self.formulas,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(self.path.parent),
                prefix=self.path.name + ".",
                suffix=".tmp",
                delete=False,
            )
            try:
                with handle:
                    json.dump(payload, handle, ensure_ascii=False, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(handle.name, self.path)
            except BaseException:
                _unlink_quietly(handle.name)
                raise
        except OSError:
            return False
        return True

    # -- изменение списка --------------------------------------------------

    def add(self, text: str) -> bool:
        """Добавляет формулу наверх списка и делает её текущей.

        :returns: ``True``, если список изменился.
        """
        text = _clean(text)
        if not text:
            return False
        changed = not self.formulas or self.formulas[0] != text
        if text in self.formulas:
            self.formulas.remove(text)
        self.formulas.insert(0, text)
        del self.formulas[MAX_FORMULAS:]
        self.current = text
        if changed:
            self.save()
        return changed

    def remove(self, text: str) -> bool:
        """Убирает формулу из списка.

        Текущая формула в поле ввода при этом не меняется: пользователь мог
        удалить строку из списка, продолжая править её текст.
        """
        text = _clean(text)
        if text not in self.formulas:
            return False
        self.formulas.remove(text)
        self.save()
        return True

    def set_current(self, text: str) -> None:
        """Запоминает содержимое поля ввода, не добавляя его в список."""
        text = _clean(text)
        if text == self.current:
            return
        self.current = text
        self.save()


def _clean(value: object) -> str:
    """Приводит значение к однострочной формуле разумной длины."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:MAX_LENGTH]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _unlink_quietly(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
