"""Приложение DP Graph Builder на Kivy.

Три экрана:

* **Меню** — оно же редактор формул: поле ввода сверху, список сохранённых
  формул снизу, кнопки справки и перехода к графику.
* **Справка** — описание языка формул, собранное из таблиц парсера.
* **График** — интерактивная координатная плоскость с жестами.

Формулы хранятся в :class:`~dp_graph.storage.FormulaStore` в каталоге данных
приложения, поэтому переживают перезапуск.
"""

from __future__ import annotations

import os

from kivy.app import App
from kivy.clock import Clock
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen, ScreenManager, SlideTransition
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

from . import theme
from .expression import Expression, ExpressionError
from .graphview import GraphView
from .help_text import build_help
from .storage import FormulaStore

__all__ = ["DPGraphBuilderApp", "main"]

STORAGE_FILENAME = "formulas.json"

# Задержка перед сохранением текста поля ввода: писать файл на каждое
# нажатие клавиши незачем.
CURRENT_SAVE_DELAY = 0.8

BAR_HEIGHT = dp(52)
ROW_HEIGHT = dp(52)


def _window():
    """Возвращает окно Kivy или ``None``, если графики нет.

    Импорт вынесен из шапки модуля намеренно: ``kivy.core.window`` при
    отсутствии дисплея не бросает исключение, а завершает процесс, что
    сделало бы модуль неимпортируемым в тестах и в headless-окружении.
    """
    try:
        from kivy.core.window import Window
    except Exception:  # pragma: no cover - зависит от окружения
        return None
    return Window


def _paint(widget: Widget, color) -> None:
    """Заливает фон виджета цветом, следя за его положением и размером."""
    with widget.canvas.before:
        Color(*color)
        rectangle = Rectangle(pos=widget.pos, size=widget.size)

    def update(*_args) -> None:
        rectangle.pos = widget.pos
        rectangle.size = widget.size

    widget.bind(pos=update, size=update)


class FlatButton(Button):
    """Кнопка без градиента и рамки — вся отрисовка задаётся цветом."""

    def __init__(self, fill=theme.CARD, ink=theme.INK, **kwargs) -> None:
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault("font_size", sp(15))
        super().__init__(**kwargs)
        self.background_color = fill
        self.color = ink
        self._fill = fill
        self.bind(state=self._on_state)

    def _on_state(self, _widget, state: str) -> None:
        # Нажатие показываем лёгким затемнением, а не сменой картинки.
        red, green, blue, alpha = self._fill
        shade = 0.88 if state == "down" else 1.0
        self.background_color = (red * shade, green * shade, blue * shade, alpha)


class FormulaRow(BoxLayout):
    """Строка списка: сама формула и кнопка её удаления."""

    def __init__(self, formula: str, on_pick, on_delete, **kwargs) -> None:
        super().__init__(orientation="horizontal", size_hint_y=None, height=ROW_HEIGHT, **kwargs)
        _paint(self, theme.CARD)

        self.pick_button = FlatButton(
            text=formula,
            fill=theme.CARD,
            ink=theme.INK,
            halign="left",
            valign="middle",
            font_size=sp(16),
        )
        self.pick_button.bind(size=self._align_text)
        self.pick_button.bind(on_release=lambda *_: on_pick(formula))

        self.delete_button = FlatButton(
            text="×",
            fill=theme.CARD,
            ink=theme.DANGER,
            size_hint_x=None,
            width=dp(52),
            font_size=sp(26),
        )
        self.delete_button.bind(on_release=lambda *_: on_delete(formula))

        self.add_widget(self.pick_button)
        self.add_widget(self.delete_button)

    def _align_text(self, widget, _size) -> None:
        widget.text_size = (widget.width - dp(16), widget.height)
        widget.padding_x = dp(8)


class MenuScreen(Screen):
    """Главный экран: ввод формулы и список сохранённых."""

    def __init__(self, controller: "DPGraphBuilderApp", **kwargs) -> None:
        super().__init__(**kwargs)
        self.controller = controller
        root = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))
        _paint(self, theme.SURFACE)

        root.add_widget(
            Label(
                text="DP Graph Builder",
                color=theme.INK,
                font_size=sp(20),
                bold=True,
                size_hint_y=None,
                height=dp(36),
            )
        )

        self.input = TextInput(
            text="",
            multiline=False,
            font_size=sp(20),
            size_hint_y=None,
            height=dp(54),
            background_normal="",
            background_active="",
            background_color=theme.FIELD,
            foreground_color=theme.INK,
            cursor_color=theme.ACCENT,
            padding=[dp(10), dp(14), dp(10), dp(10)],
            hint_text="Например: sin(x)/x",
            write_tab=False,
        )
        self.input.bind(text=self._on_text)
        self.input.bind(on_text_validate=lambda *_: self._open_graph())
        root.add_widget(self.input)

        self.status = Label(
            text="",
            color=theme.DANGER,
            font_size=sp(13),
            size_hint_y=None,
            height=dp(30),
            halign="left",
            valign="middle",
            shorten=True,
        )
        self.status.bind(size=lambda w, _s: setattr(w, "text_size", w.size))
        root.add_widget(self.status)

        buttons = BoxLayout(orientation="horizontal", spacing=dp(10), size_hint_y=None, height=BAR_HEIGHT)
        self.help_button = FlatButton(text="Справка", fill=theme.CARD, ink=theme.INK)
        self.help_button.bind(on_release=lambda *_: controller.show_help())
        self.plot_button = FlatButton(text="Построить график", fill=theme.ACCENT, ink=theme.ACCENT_INK, bold=True)
        self.plot_button.bind(on_release=lambda *_: self._open_graph())
        buttons.add_widget(self.help_button)
        buttons.add_widget(self.plot_button)
        root.add_widget(buttons)

        self.list_title = Label(
            text="Сохранённые формулы",
            color=theme.INK_MUTED,
            font_size=sp(13),
            size_hint_y=None,
            height=dp(26),
            halign="left",
            valign="middle",
        )
        self.list_title.bind(size=lambda w, _s: setattr(w, "text_size", w.size))
        root.add_widget(self.list_title)

        scroll = ScrollView(bar_width=dp(3), do_scroll_x=False)
        self.list_layout = GridLayout(cols=1, spacing=dp(1), size_hint_y=None, padding=[0, 0, 0, dp(4)])
        self.list_layout.bind(minimum_height=self.list_layout.setter("height"))
        scroll.add_widget(self.list_layout)
        root.add_widget(scroll)

        self.add_widget(root)

    # -- реакция на ввод ---------------------------------------------------

    def _on_text(self, _widget, text: str) -> None:
        # validate() возвращает None для корректной формулы, а Label.text
        # не принимает None — приводим к пустой строке.
        self.status.text = (Expression.validate(text) or "") if text.strip() else ""
        self.controller.schedule_current_save(text)

    def _open_graph(self) -> None:
        self.controller.open_graph(self.input.text)

    # -- список ------------------------------------------------------------

    def refresh(self) -> None:
        """Перестраивает список формул по содержимому хранилища."""
        self.list_layout.clear_widgets()
        formulas = self.controller.store.formulas
        if not formulas:
            empty = Label(
                text="Список пуст. Введите формулу и постройте график.",
                color=theme.INK_MUTED,
                font_size=sp(14),
                size_hint_y=None,
                height=ROW_HEIGHT,
            )
            self.list_layout.add_widget(empty)
            return
        for formula in formulas:
            self.list_layout.add_widget(
                FormulaRow(formula, on_pick=self._pick, on_delete=self._delete)
            )

    def _pick(self, formula: str) -> None:
        """Нажатие на формулу переносит её в поле ввода для правки."""
        self.input.text = formula
        self.input.cursor = (len(formula), 0)

    def _delete(self, formula: str) -> None:
        self.controller.store.remove(formula)
        self.refresh()

    def set_text(self, text: str) -> None:
        self.input.text = text


class HelpScreen(Screen):
    """Экран справки по языку формул."""

    def __init__(self, controller: "DPGraphBuilderApp", **kwargs) -> None:
        super().__init__(**kwargs)
        _paint(self, theme.SURFACE)
        root = BoxLayout(orientation="vertical")

        root.add_widget(_top_bar("Справка", lambda: controller.show_menu()))

        scroll = ScrollView(bar_width=dp(3), do_scroll_x=False)
        self.body = Label(
            text=build_help(),
            markup=True,
            color=theme.INK,
            font_size=sp(15),
            size_hint_y=None,
            halign="left",
            valign="top",
            padding=(dp(14), dp(14)),
        )
        self.body.bind(width=lambda w, value: setattr(w, "text_size", (value - dp(28), None)))
        self.body.bind(texture_size=lambda w, value: setattr(w, "height", value[1] + dp(28)))
        scroll.add_widget(self.body)
        root.add_widget(scroll)
        self.add_widget(root)


class GraphScreen(Screen):
    """Экран визуализации: график во весь экран и панель управления."""

    def __init__(self, controller: "DPGraphBuilderApp", **kwargs) -> None:
        super().__init__(**kwargs)
        self.controller = controller
        _paint(self, theme.SURFACE)
        root = BoxLayout(orientation="vertical")

        bar = BoxLayout(orientation="horizontal", size_hint_y=None, height=BAR_HEIGHT, spacing=dp(1))
        _paint(bar, theme.BORDER)

        back = FlatButton(text="‹ Меню", fill=theme.CARD, ink=theme.INK, size_hint_x=None, width=dp(96))
        back.bind(on_release=lambda *_: controller.show_menu())
        bar.add_widget(back)

        self.title = Label(text="", color=theme.INK, font_size=sp(16), shorten=True)
        _paint(self.title, theme.CARD)
        bar.add_widget(self.title)

        reset = FlatButton(text="Сброс", fill=theme.CARD, ink=theme.ACCENT, size_hint_x=None, width=dp(88))
        reset.bind(on_release=lambda *_: self.graph.reset_view())
        bar.add_widget(reset)

        root.add_widget(bar)

        self.graph = GraphView()
        self._shown: str | None = None
        root.add_widget(self.graph)
        self.add_widget(root)

    def show(self, text: str) -> None:
        """Показывает формулу, разбирая её заново.

        Смена формулы возвращает вид к исходному: масштаб, подобранный под
        предыдущую кривую, для новой чаще всего бессмыслен. Повторное
        открытие той же формулы положение сохраняет.
        """
        changed = text != self._shown
        self._shown = text
        self.title.text = f"y = {text}"
        try:
            self.graph.set_expression(Expression(text))
        except ExpressionError as error:
            self.graph.set_expression(None, str(error))
        if changed:
            self.graph.reset_view()


def _top_bar(title: str, on_back) -> BoxLayout:
    """Полоса заголовка с кнопкой возврата."""
    bar = BoxLayout(orientation="horizontal", size_hint_y=None, height=BAR_HEIGHT, spacing=dp(1))
    _paint(bar, theme.BORDER)

    back = FlatButton(text="‹ Меню", fill=theme.CARD, ink=theme.INK, size_hint_x=None, width=dp(96))
    back.bind(on_release=lambda *_: on_back())
    bar.add_widget(back)

    label = Label(text=title, color=theme.INK, font_size=sp(16), bold=True)
    _paint(label, theme.CARD)
    bar.add_widget(label)
    return bar


class DPGraphBuilderApp(App):
    """Точка сборки: хранилище, экраны и переходы между ними."""

    title = "DP Graph Builder"

    def __init__(self, storage_path: str | os.PathLike[str] | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._storage_path = storage_path
        self.store: FormulaStore | None = None
        self._save_event = None

    def build(self):
        path = self._storage_path or os.path.join(self.user_data_dir, STORAGE_FILENAME)
        self.store = FormulaStore(path)

        self.manager = ScreenManager(transition=SlideTransition(duration=0.18))
        self.menu_screen = MenuScreen(self, name="menu")
        self.help_screen = HelpScreen(self, name="help")
        self.graph_screen = GraphScreen(self, name="graph")
        for screen in (self.menu_screen, self.help_screen, self.graph_screen):
            self.manager.add_widget(screen)

        # Последняя использованная формула сразу в поле ввода.
        self.menu_screen.set_text(self.store.current)
        self.menu_screen.refresh()

        window = _window()
        if window is not None:
            window.clearcolor = theme.SURFACE
            # Поднимаем поле ввода над экранной клавиатурой.
            window.softinput_mode = "below_target"
            window.bind(on_keyboard=self._on_keyboard)
        return self.manager

    # -- навигация ---------------------------------------------------------

    def show_menu(self) -> None:
        self.manager.transition.direction = "right"
        self.manager.current = "menu"
        self.menu_screen.refresh()

    def show_help(self) -> None:
        self.manager.transition.direction = "left"
        self.manager.current = "help"

    def open_graph(self, text: str) -> None:
        """Проверяет формулу, добавляет её в список и открывает график."""
        text = text.strip()
        if not text:
            self.menu_screen.status.text = "Введите формулу"
            return
        error = Expression.validate(text)
        if error:
            self.menu_screen.status.text = error
            return

        # Успешно построенная формула сама попадает в список.
        self.store.add(text)
        self.menu_screen.set_text(text)
        self.menu_screen.refresh()

        self.graph_screen.show(text)
        self.manager.transition.direction = "left"
        self.manager.current = "graph"

    # -- сохранение текущей формулы ---------------------------------------

    def schedule_current_save(self, text: str) -> None:
        """Откладывает запись поля ввода на диск, объединяя частые правки."""
        if self.store is None:
            return
        if self._save_event is not None:
            self._save_event.cancel()
        self._save_event = Clock.schedule_once(
            lambda _dt: self.store.set_current(text), CURRENT_SAVE_DELAY
        )

    # -- системная кнопка «назад» -----------------------------------------

    def _on_keyboard(self, _window, key: int, *_args) -> bool:
        # 27 — Esc на настольной машине и аппаратная кнопка «назад» на Android.
        if key == 27 and self.manager.current != "menu":
            self.show_menu()
            return True
        return False

    def on_pause(self) -> bool:
        self._flush()
        return True

    def on_stop(self) -> None:
        self._flush()

    def _flush(self) -> None:
        if self._save_event is not None:
            self._save_event.cancel()
            self._save_event = None
        if self.store is not None:
            self.store.set_current(self.menu_screen.input.text)


def main() -> None:
    """Запускает приложение."""
    DPGraphBuilderApp().run()
