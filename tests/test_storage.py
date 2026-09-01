"""Тесты хранения списка формул."""

from __future__ import annotations

import json

import pytest

from dp_graph.storage import DEFAULT_FORMULAS, MAX_FORMULAS, MAX_LENGTH, FormulaStore


@pytest.fixture
def path(tmp_path):
    return tmp_path / "data" / "formulas.json"


def test_first_run_seeds_defaults(path) -> None:
    store = FormulaStore(path)
    assert store.formulas == list(DEFAULT_FORMULAS)
    assert store.current == DEFAULT_FORMULAS[0]


def test_survives_restart(path) -> None:
    store = FormulaStore(path)
    store.add("x^3 + 1")
    reopened = FormulaStore(path)
    assert reopened.formulas[0] == "x^3 + 1"
    assert reopened.current == "x^3 + 1"


def test_add_moves_existing_to_top_without_duplicating(path) -> None:
    store = FormulaStore(path)
    store.add("cos(x)")
    store.add("tan(x)")
    store.add("cos(x)")
    assert store.formulas[0] == "cos(x)"
    assert store.formulas.count("cos(x)") == 1


def test_remove(path) -> None:
    store = FormulaStore(path)
    target = store.formulas[1]
    assert store.remove(target)
    assert target not in store.formulas
    assert not store.remove(target)
    assert FormulaStore(path).formulas == store.formulas


def test_remove_keeps_the_edited_text(path) -> None:
    # Удаление строки из списка не должно очищать поле ввода: пользователь
    # мог убрать запись, продолжая править её текст.
    store = FormulaStore(path)
    store.add("sin(2x)")
    store.remove("sin(2x)")
    assert store.current == "sin(2x)"


def test_set_current_does_not_add_to_the_list(path) -> None:
    store = FormulaStore(path)
    before = list(store.formulas)
    store.set_current("недописанная формула")
    assert store.formulas == before
    assert FormulaStore(path).current == "недописанная формула"


def test_blank_input_is_ignored(path) -> None:
    store = FormulaStore(path)
    before = list(store.formulas)
    assert not store.add("   ")
    assert store.formulas == before


def test_whitespace_is_normalised(path) -> None:
    store = FormulaStore(path)
    store.add("  sin( x )   +  1 ")
    assert store.formulas[0] == "sin( x ) + 1"


def test_length_and_count_are_capped(path) -> None:
    store = FormulaStore(path)
    store.add("x" * (MAX_LENGTH * 3))
    assert len(store.formulas[0]) == MAX_LENGTH
    for index in range(MAX_FORMULAS + 40):
        store.add(f"x + {index}")
    assert len(store.formulas) == MAX_FORMULAS


# --------------------------------------------------------------------------
# Устойчивость к плохому файлу
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    ['{"это не json', "", "[]", '{"formulas": "не список"}', '{"formulas": [1, 2, null]}'],
)
def test_broken_file_falls_back_to_defaults(path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    store = FormulaStore(path)
    assert store.formulas == list(DEFAULT_FORMULAS)


def test_unwritable_path_does_not_raise(tmp_path) -> None:
    # Запись может не удаться (нет прав, кончилось место) — приложение
    # обязано продолжить работать, потеряв только сохранение.
    # Каталогом на пути делаем обычный файл: создать его как папку нельзя.
    blocker = tmp_path / "blocker"
    blocker.write_text("это файл, а не каталог", encoding="utf-8")
    store = FormulaStore(tmp_path / "formulas.json")
    store.path = blocker / "nested" / "formulas.json"
    assert store.save() is False


def test_written_file_is_valid_json(path) -> None:
    store = FormulaStore(path)
    store.add("sin(x) + 1")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert data["current"] == "sin(x) + 1"
    assert "sin(x) + 1" in data["formulas"]


def test_no_temporary_files_are_left_behind(path) -> None:
    store = FormulaStore(path)
    store.add("x + 1")
    assert [item.name for item in path.parent.iterdir()] == [path.name]
