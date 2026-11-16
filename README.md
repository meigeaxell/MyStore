# MobileStore
Начальный каркас desktop-приложения для учёта магазина мобильной техники.

## Запуск на Fedora
```bash
cd MobileStore
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m app.main
```

Проверка: `pytest`

Текущий каркас содержит главное окно PySide6, базовое подключение SQLite через SQLAlchemy и заготовки структуры модулей. Бизнес-операции и модели будут добавляться по дорожной карте.
