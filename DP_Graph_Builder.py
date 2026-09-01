"""Запуск под историческим именем файла.

Логика приложения живёт в пакете :mod:`dp_graph`, а точкой входа для сборки
под Android служит ``main.py``. Этот файл сохранён, чтобы продолжала
работать привычная команда ``python DP_Graph_Builder.py``.
"""

from dp_graph.app import main

if __name__ == "__main__":
    main()
