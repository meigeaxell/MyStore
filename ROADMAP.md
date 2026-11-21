# MobileStore — UI/UX Redesign & Workflow Refactoring Roadmap

## Completed Stages

### Stage 0 — Full UI/UX & Technical Audit
- Audited all database models, Alembic migrations (at head `e7b2a41c90f4`), services, and PySide6 UI modules.
- Diagnosed root causes of visual and layout issues from user screenshots:
  - **Dark/black elements and borders in Sales & Tabs**: Missing `QTabWidget::pane` and `QTabBar::tab` styling in `app/ui/theme.py` combined with missing `#page` objectName on `SalesPage`, causing Qt on Linux to inherit dark OS theme colors.
  - **Overlapping fields & collapsed tables in Purchases**: 12 sections packed into a non-scrollable `QVBoxLayout` where `items_table` and `payments_table` had `setMaximumHeight(...)` without `setMinimumHeight(...)`, collapsing tables to header bars and compressing `QFormLayout` rows on smaller windows.

### Stage 1 — Unified Products & Inventory (`Товары и склад`)
- Merged `Каталог товаров` and `Склад` into a single unified **`Товары и склад`** module (`app/ui/stock_page.py`, `app/ui/main_window.py`).
- Preserved the business distinction between `Product` (catalog item / quantitative stock) and `StockItem` (individual serialized IMEI device).
- Added summary cards (Catalog count, IMEI devices in stock with New/Used breakdown, Low stock, Out of stock).
- Added unified search (by Name, Brand, Model, SKU, or IMEI), category filter, and stock status filter (`В наличии`, `Есть Б/У устройства`, `Низкий остаток`, `Нет в наличии`).
- Placed product actions (`📱 Карточка товара и устройства (IMEI)`, `✏ Редактировать товар`, `+ Добавить IMEI к выбранному`, `📜 История движений`) directly below the table.
- Created a unified Product Details & IMEI dialog (`StockItemDialog`) with tabs for IMEI registration/list and product movement history.
- Moved product, category, and stock-item database mutations into `app/repositories/product_repository.py`.

### Stage 2 — Used Device Registration & Receipt-Free Trade-In Workflow
- Enabled direct intake of used (and new) devices by IMEI with condition (`Новый` / `Б/У`), acquisition source (`Поставщик`, `Выкуп у клиента`, `Trade-In`, `Ввод остатков`), cost basis, and condition notes.
- Reworked Trade-In (`app/services/exchange_service.py`, `app/ui/exchange_page.py`) so an original sale receipt is no longer required:
  - Added `ExchangeService.inspect_incoming_imei()` to check if an incoming IMEI is new to the database, previously sold (auto-selecting the model and showing historical sale context), or already `in_stock` (blocking duplicate intake).
  - Incoming Trade-In devices are automatically registered or returned into `StockItem` as `in_stock` (`condition="used"`, `acquisition_source="trade_in"`) and increment `Product.stock_quantity`.
  - Preserved all exchange business rules (replacement price `>=` old valuation, no cash refunds, mixed USD/TMT additional payment recording, and full exchange history).

### Stage 3 — Purchase Interface, Dropdowns & Tables
- Refactored `PurchaseDialog` and `PurchaseDetailsDialog` (`app/ui/purchase_page.py`) with responsive `QScrollArea` content containers and pinned bottom action bars.
- Applied `style_combo()` with a dedicated light-palette `QListView` popup across all dropdowns so options never overlap adjacent inputs.
- Set proper minimum heights on `items_table` and `payments_table` and positioned `📱 Указать IMEI для выбранной позиции`, `Удалить выбранную позицию`, and `Удалить выбранную оплату` directly below their respective tables.

### Stage 4 — Sales & Cash Management Visual Redesign
- Added global light-theme rules for `QTabWidget::pane`, `QTabBar::tab`, `QListWidget`, `QListView`, `#dangerBtn`, and `#secondaryBtn` in `app/ui/theme.py`.
- Set `self.setObjectName("page")` on `SalesPage` (`app/ui/sales_page.py`) to eliminate dark/black backgrounds and borders.
- Added explicit cart action buttons (`💲 Указать цену продажи`, `🔢 Изменить количество`, `Удалить выбранную позицию`) directly below the cart table and a `Ровно по чеку` quick-fill link in the payment panel.
- Added a visible `📄 Открыть документ` button in the Cash Management journal (`app/ui/finance_page.py`).

### Stage 5 — Unified Search & Visual Selection Dialogs
- Created `app/ui/selection_dialogs.py` with two reusable context-aware dialogs:
  - `CatalogProductSelectorDialog` (search, category filter, inline `+ Создать новый товар в каталоге`) integrated into Purchases and Trade-In intake.
  - `InventorySelectorDialog` (search, category filter, type/condition filter for New IMEI / Used IMEI / Accessories, availability indicators) integrated into Sales (`Найти / Выбрать со склада…`) and Trade-In replacement selection.

### Stage 6 & Stage 7 — Responsive Layout, Dashboard Analytics & UI Unification
- Unified shared UI builders (`make_button`, `configure_table`, `style_combo`, `make_stat_card`, `money_str`) in `app/ui/widgets.py`.
- Implemented interactive time-range switching (`1Д`, `1Н`, `1М`, `6М`, `1Г`) on `DashboardPage` (`app/ui/dashboard_page.py`):
  - Switching the period dynamically updates the diagram buckets (hourly for `1Д`, daily for `1Н` and `1М`, monthly for `6М` and `1Г`), the top 4 summary cards (`Продажи`, `Обмены / Отмены`, `Закупки`, `Количество чеков`), the Gross Profit KPI cards (`Валовая прибыль USD / TMT`), and the header date range badge.
  - Added an interactive hover popup at the top of `BarChart` (`app/ui/widgets.py`) showing the period title, receipt count, sales revenue (`USD` / `TMT`), and gross profit / earnings (`USD` / `TMT`) when hovering over any bar.
- Eliminated hundreds of lines of duplicate inline CSS from `category_dialog.py`, `category_management_dialog.py`, `product_dialog.py`, `stock_page.py`, `purchase_page.py`, and `sales_page.py`.
- Verified all files pass `ruff check app` and headless Qt initialization without errors.

## Architectural Decisions
- **Zero Database Schema / Model Edits**: Reused existing `Product`, `StockItem` (with `acquisition_source` and `notes`), and `DeviceExchange` (with nullable `original_sale_id` / `original_sale_item_id` and `old_condition`) models without adding new tables or modifying models.
- **Repository & Service Layer Separation**: UI handlers call `app/repositories/product_repository.py` and `app/services/*` rather than executing raw SQLAlchemy mutations inside button callbacks.

### Stage 8 — Desktop POS Acceleration, Shift Closing, Smart Purchases & Global Search (`Ctrl+K`)
- **1-Step Negotiated POS (`app/ui/sales_page.py`)**:
  - Direct inline editing of `Кол-во`, `Себестоимость`, and `Цена торга` directly in the cart table (with automatic focus on `Цена торга` when adding an item, and live per-line & total profit display).
  - Default **`✔ Оплачено полностью (1 клик)`** payment mode automatically synchronizes payment with the negotiated cart total; manual **`⚖ В долг / 2 валюты / Сдача`** mode is available on toggle.
  - Safety checks warning before completing sales with `0.00` price or below cost basis.
  - Partial IMEI search (4+ digits), quick bar of top-5 popular products, held sales drafts (`⏸ Отложить чек` / `📂 Отложенные`), and keyboard shortcuts (`F2`, `F3`, `F4`, `F9`, `Delete`).
- **Receipt & Z-Report PDF Printing (`app/ui/receipt_printer.py`)**:
  - Added PDF receipt export (`🖨 Печать / PDF чека`) in `SalesPage` and `SaleDetailsDialog`, plus Z-report export for shift closing.
- **Default Cost Basis in Product Card (`app/ui/product_dialog.py`, `app/services/settings_service.py`, `app/services/sales_service.py`)**:
  - Added `Себестоимость за шт.` (USD/TMT) right in `ProductDialog` and automatic fallback resolution in `SalesService._resolve_item_cost_basis()` without DB migrations.
- **Smart Purchases (`app/ui/purchase_page.py`)**:
  - Editable supplier autocomplete combo from purchase history, automatic last-purchase-cost pre-fill on product selection, `⚡ Заполнить дефицитные товары`, and `🔁 Повторить выбранную закупку`.
- **Inventory Age & Stale Stock (`app/repositories/product_repository.py`, `app/ui/stock_page.py`)**:
  - Displays days in stock on IMEI devices (`В наличии (X дн.)`) and adds a `Залежавшиеся (> 30 дней)` filter.
- **Shift Closing & Cash Reconciliation (`app/ui/finance_page.py`)**:
  - Added `ShiftCloseDialog` (`🔒 Закрытие смены / Сверка`) comparing expected vs. actual cash balances in USD and TMT with one-click adjustment creation and PDF Z-report export.
- **Global Smart Search (`Ctrl+K`), Window Persistence & Table Column Menu (`app/ui/quick_search_dialog.py`, `app/ui/main_window.py`, `app/ui/widgets.py`)**:
  - Added unified `QuickSearchDialog` searching Products, full/partial IMEIs, Receipts/Customers, and Purchases/Suppliers.
  - Added `QSettings` window geometry and last-opened tab persistence, plus right-click table header column visibility toggle.

### Stage 9 — MobileStore Scanner (Local Wi-Fi WebSocket Server & Android App)
- **WebSocket Protocol v1 (`docs/MOBILE_PROTOCOL.md`, `app/services/mobile_protocol.py`)**:
  - Decoupled JSON protocol v1 with PIN authentication, `request_id` idempotency cache (protecting mutating commands from network retries), IMEI Luhn validation, and full integration with existing `product_repository`, `purchase_service`, `SalesService`, and `SettingsService`.
- **Desktop WebSocket Server & UI (`app/services/mobile_ws_server.py`, `app/ui/main_window.py`, `app/ui/settings_page.py`, `app/ui/sales_page.py`, `mobilestore.spec`)**:
  - Built directly on `PySide6.QtWebSockets.QWebSocketServer` (zero extra Python dependencies, non-blocking Qt event loop, PyInstaller hiddenimports updated).
  - Supports multiple simultaneous smartphones with reconnect deduplication by `device_id`.
  - Automatically adds confirmed items from smartphones into the active `SalesPage` draft cart, switches to `Продажи и касса`, brings the window to front, and updates the status bar (`📱 Сканеров: N`) and Settings tab (`📱 Мобильный сканер (Android)`).
- **Android Companion Project (`android_scanner/`)**:
  - Standalone Kotlin + Jetpack Compose + CameraX + bundled offline ML Kit (Barcode + OCR IMEI with Luhn + 2-frame consensus) + OkHttp WebSocket (auto-reconnect, heartbeat, sticky `request_id`) + Room local draft persistence.
  - Implements all 5 screens: Always-on Sale Scanner (no "Scan" button, auto-pause on product card, negotiated price + USD/TMT), Receiving (IMEI batch scanning, OCR confirmation dialog, Room drafts), Catalog, Categories, and Connection Settings.
- **Automated Verification (`tests/test_mobile_protocol.py`)**:
  - Verified Luhn validation, auth/version guards, multi-device WebSocket connections & reconnect deduplication, duplicate IMEI rejection, concurrent cart conflicts, idempotent retries, and catalog/category operations.


