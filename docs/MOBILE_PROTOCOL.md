# MobileStore WebSocket Protocol Specification (v1)

Документ описывает локальный протокол обмена сообщениями между настольным приложением **MobileStore** (центральный сервер на базе `PySide6.QtWebSockets`) и мобильными клиентами **MobileStore Scanner** (Android / Kotlin).

- **Транспорт**: WebSocket (`ws://<LAN_IP>:<PORT>`, порт по умолчанию `8765`).
- **Кодировка**: UTF-8 JSON (текстовые фреймы WebSocket).
- **Работа без интернета**: полностью в локальной Wi-Fi сети магазина.
- **Версия протокола**: `protocol_version = 1`.

---

## 1. Общая структура сообщений

### Запрос (Android → Компьютер)
```json
{
  "protocol_version": 1,
  "type": "scan_code",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "device_id": "android-device-uuid",
  "payload": {}
}
```

- `protocol_version` (`int`, обязательно) — версия протокола (`1`).
- `type` (`string`, обязательно) — тип команды.
- `request_id` (`string`, обязательно) — уникальный UUID v4 запроса (используется для связывания ответа и **идемпотентности** мутирующих операций).
- `device_id` (`string`, обязательно) — постоянный уникальный идентификатор смартфона.
- `payload` (`object`, опционально, по умолчанию `{}`) — параметры команды.

### Ответ (Компьютер → Android)
```json
{
  "protocol_version": 1,
  "type": "product_card",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "ok": true,
  "data": {},
  "error": null
}
```

При ошибке `ok = false`, `data = null`:
```json
{
  "protocol_version": 1,
  "type": "error",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "ok": false,
  "data": null,
  "error": {
    "code": "ALREADY_SOLD",
    "message": "Устройство с IMEI 356938035643809 уже продано."
  }
}
```

---

## 2. Идемпотентность и защита от повторных операций

Для всех изменяющих команд (`add_to_sale`, `product_create`, `product_update`, `category_create`, `category_update`, `category_deactivate`, `receive_purchase`) сервер хранит кэш результатов по ключу `(device_id, request_id)`.
Если связь оборвалась до получения ответа телефоном и клиент отправил команду повторно с тем же `request_id`, сервер **не выполняет** операцию повторно, а возвращает сохранённый ответ.

---

## 3. Типы сообщений

### 3.1. Авторизация (`auth` → `auth_ok` / `auth_error`)
Первое сообщение после установки WebSocket-соединения. Любые другие команды до успешной авторизации отклоняются с кодом `UNAUTHORIZED`.

**Запрос `payload`**:
```json
{
  "token": "482910",
  "device_id": "android-device-uuid",
  "device_name": "Samsung Galaxy A54 (Кассир 1)",
  "app_version": "1.0.0"
}
```

**Ответ `auth_ok` (`data`)**:
```json
{
  "store_name": "MobileStore",
  "default_currency": "TMT",
  "default_exchange_rate": "19.5000",
  "server_version": "0.1.0",
  "connected_devices_count": 1
}
```

### 3.2. Проверка связи (`ping` → `pong`)
**Запрос `payload`**: `{}`  
**Ответ `pong` (`data`)**: `{"server_time": "2026-11-19T14:45:00"}`

### 3.3. Сканирование кода или наклейки коробки (`scan_code` → `product_card` / `scan_not_found` / `scan_multiple`)
Поддерживает как одиночный `code`, так и пакетный мульти-скан всех кодов с наклейки коробки (`codes`, `imei1`, `imei2`, `serial_number`, `barcode`). При неточном чтении 1–3 цифр IMEI или символов S/N сервер выполняет нечёткий поиск по большинству совпавших символов (`>= 80%`) и выставляет `requires_confirmation: true`.

**Запрос `payload`**:
```json
{
  "code": "356938035643809",
  "codes": ["356938035643809", "356938035643817", "F2LZN123ABCD"],
  "imei1": "356938035643809",
  "imei2": "356938035643817",
  "serial_number": "F2LZN123ABCD",
  "barcode": "194253775812",
  "source": "multi",
  "mode": "sale"
}
```
- `source`: `"barcode"` | `"qr"` | `"ocr"` | `"multi"` | `"manual"`
- `mode`: `"sale"` | `"receive"` | `"catalog"`

**Ответ `product_card` (`data`)**:
```json
{
  "product_id": 12,
  "stock_item_id": 45,
  "sku": "PRD_000012",
  "name": "iPhone 15 Pro",
  "brand": "Apple",
  "model": "A3102",
  "specification": "256GB / Black Titanium",
  "category_id": 1,
  "category_name": "Смартфоны",
  "imei": "356938035643809",
  "imei2": "356938035643817",
  "serial_number": "F2LZN123ABCD",
  "condition": "new",
  "stock_quantity": 3,
  "unit_cost": "920.00",
  "cost_currency": "USD",
  "default_currency": "TMT",
  "exchange_rate": "19.5000",
  "photo_url": null,
  "availability_status": "available",
  "availability_message": "Доступно для продажи",
  "match_type": "exact",
  "match_score": 100,
  "match_detail": "Точное совпадение (IMEI 1)",
  "scanned_code": "356938035643809",
  "matched_code": "356938035643809",
  "requires_confirmation": false
}
```
Возможные значения `availability_status`: `"available"`, `"sold"`, `"out_of_stock"`, `"in_cart"`.  
Возможные значения `match_type`: `"exact"` (100% совпадение) или `"fuzzy"` (совпадение по большинству цифр — требует явного подтверждения на смартфоне).

### 3.4. Подтверждение добавления в продажу (`add_to_sale` → `operation_ok`)
Добавляет товар в черновик текущей продажи в `SalesPage` на компьютере (не закрывает чек и не списывает кассу до подтверждения кассиром на ПК). Автоматически открывает вкладку «Продажи и касса».

**Запрос `payload`**:
```json
{
  "product_id": 12,
  "stock_item_id": 45,
  "imei": "356938035643809",
  "quantity": 1,
  "unit_price": "19500.00",
  "currency": "TMT"
}
```

**Ответ `operation_ok` (`data`)**:
```json
{
  "message": "Товар «iPhone 15 Pro» добавлен в текущую продажу",
  "cart_items_count": 1,
  "cart_total": "19500.00",
  "currency": "TMT"
}
```

### 3.5. Отмена операции (`cancel_operation` → `operation_ok`)
**Запрос `payload`**: `{"target_request_id": "...", "reason": "user_cancelled"}`

### 3.6. Проверка IMEI перед приёмкой (`check_imei` → `imei_check_result`)
**Запрос `payload`**: `{"imei1": "356938035643809", "imei2": null}`  
**Ответ (`data`)**:
```json
{
  "imei1": "356938035643809",
  "luhn_valid": true,
  "exists_in_db": false,
  "can_receive": true,
  "message": "IMEI корректен и свободен для приёмки"
}
```

### 3.7. Оформление приёмки / закупки (`receive_purchase` → `operation_ok`)
Использует существующий сервис `purchase_service.create_purchase(...)`.

**Запрос `payload`**:
```json
{
  "supplier_name": "Official Distributor",
  "currency": "USD",
  "exchange_rate": "19.5000",
  "note": "Приёмка через мобильный сканер",
  "items": [
    {
      "product_id": 12,
      "quantity": 2,
      "unit_cost": "920.00",
      "imeis": [
        {"imei1": "356938035643809", "imei2": null, "serial_number": null, "condition": "new"},
        {"imei1": "356938035643817", "imei2": null, "serial_number": null, "condition": "new"}
      ]
    }
  ]
}
```

**Ответ `operation_ok` (`data`)**:
```json
{
  "purchase_id": 18,
  "message": "Закупка №18 успешно проведена (принято 2 ед.)"
}
```

### 3.8. Каталог и товары
- `catalog_list`: `payload = {"query": "", "category_id": null, "limit": 100}` → `{"products": [...]}`
- `product_details`: `payload = {"product_id": 12}` → `{"product": {...}, "devices": [...]}`
- `product_create`: `payload = {"name": "...", "category_id": 1, "brand": "...", "model": "...", "specification": "...", "stock_quantity": 0, "min_stock_quantity": 2, "unit_cost": "0.00", "cost_currency": "USD", "allow_duplicate": false}` → `{"product": {...}}`
- `product_update`: `payload = {"product_id": 12, ...}` → `{"product": {...}}`

### 3.9. Категории
- `category_list`: `payload = {"active_only": false}` → `{"categories": [{"id", "name", "code", "is_active", "product_count"}]}`
- `category_create`: `payload = {"name": "Смартфоны"}` → `{"category": {...}}`
- `category_update`: `payload = {"category_id": 1, "name": "Смартфоны Apple"}` → `{"category": {...}}`
- `category_deactivate`: `payload = {"category_id": 1}` → `{"category_id": 1, "active_products_count": 0}`

---

## 4. Коды ошибок

| Код | Описание |
|---|---|
| `INVALID_JSON` | Некорректный формат JSON |
| `UNSUPPORTED_VERSION` | Неподдерживаемая версия протокола |
| `UNAUTHORIZED` | Устройство не авторизовано или неверный PIN/токен |
| `VALIDATION_ERROR` | Отсутствуют обязательные поля или некорректные числа |
| `NOT_FOUND` | Товар, категория или IMEI не найдены |
| `ALREADY_SOLD` | Устройство с указанным IMEI уже продано |
| `OUT_OF_STOCK` | Нулевой остаток товара на складе |
| `ALREADY_IN_CART` | Устройство с этим IMEI уже добавлено в текущую продажу |
| `DUPLICATE_IMEI` | IMEI уже зарегистрирован в базе данных |
| `DUPLICATE_PRODUCT` | Товар с такими же характеристиками уже существует |
| `UNKNOWN_COMMAND` | Неизвестный тип сообщения |
| `INTERNAL_ERROR` | Внутренняя ошибка сервера / БД |
