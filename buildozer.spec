# Сборка APK: pip install buildozer && buildozer -v android debug
# Готовый файл появится в bin/.

[app]
title = DP Graph Builder
package.name = dpgraphbuilder
package.domain = org.dpsmpx

source.dir = .
source.include_exts = py
# В APK не должны попадать тесты и служебные файлы.
source.exclude_dirs = tests, bin, .buildozer, .git, __pycache__
source.exclude_patterns = buildozer.spec, pyproject.toml, README.md, LICENSE

version = 2.0.0

# Только Kivy: вычисления идут на чистом Python, matplotlib и numpy не нужны,
# что заметно сокращает время сборки и размер пакета.
requirements = python3,kivy==2.3.1

orientation = portrait
fullscreen = 0

# Приложение работает целиком офлайн и ничего не читает за пределами своего
# каталога данных, поэтому разрешения ему не требуются.
android.permissions =

android.api = 34
android.minapi = 24
android.archs = arm64-v8a, armeabi-v7a
android.allow_backup = True

[buildozer]
log_level = 2
warn_on_root = 1
