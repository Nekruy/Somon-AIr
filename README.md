# Somon Air MVP

Дашборд для авиакомпании Somon Air с ML-прогнозом задержек рейсов.

## Быстрый старт

### 1. Установить зависимости

```bash
pip install -r requirements.txt
```

### 2. Запустить сервер

```bash
cd backend
uvicorn main:app --reload --port 8000
```

### 3. Открыть браузер

```
http://localhost:8000
```

## Возможности

- **Таблица рейсов** — расписание с маршрутами, воздушными судами, статусами и задержками
- **ML-прогноз риска** — для каждого рейса модель предсказывает риск задержки (LOW / MEDIUM / HIGH)
- **Ручной прогноз** — форма для расчёта вероятности задержки по параметрам рейса
- **Статистика** — общее число рейсов, процент вовремя, средняя задержка

## Стек

| Компонент | Технология |
|-----------|-----------|
| Backend | Python 3.11+, FastAPI, Uvicorn |
| База данных | SQLite (auto-created) |
| ML | scikit-learn GradientBoostingClassifier |
| Frontend | Vanilla HTML/CSS/JS |

## Маршруты (хаб Душанбе — TJK)

TJK ↔ DME, DXB, IST, SVO, FRU, URC, KBL, TSE

## Структура проекта

```
somon-air-mvp/
├── backend/
│   ├── main.py          # FastAPI сервер
│   └── delay_model.py   # ML модель прогноза задержек
├── frontend/
│   └── index.html       # Дашборд (SPA)
├── requirements.txt
├── CLAUDE.md
└── README.md
```

## Заметки

- `flights.db` и `delay_model.pkl` создаются автоматически при первом запуске.
- Для переобучения модели — удалить `backend/delay_model.pkl`.
