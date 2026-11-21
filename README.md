# MobileStore

Desktop application for managing a mobile phones, electronics, and accessories retail store, built with **Python**, **PySide6**, **SQLite**, **SQLAlchemy**, and **Alembic**.

---

## 1. Development & Launch (Linux / Fedora)

```bash
cd ~/Projects/MobileStore
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# Apply database migrations
alembic upgrade head

# Launch the application
python -m app.ui.run_preview
# or
python -m app.main
```

### Code Quality Check
```bash
ruff check app
```

---

## 2. Implemented Modules & Architecture

1. **Главная панель (`DashboardPage`)**:
   - Live USD and TMT cash balances, monthly gross profit (historical COGS), today's & monthly sales revenue, monthly purchases, 4-category debt summary, inventory breakdown (New phones, Used phones, Accessories), low-stock alerts, and recent operations log.
2. **Каталог товаров (`CatalogPage`, `ProductDialog`, `CategoryManagementDialog`)**:
   - Product and category management with auto-generated SKUs (`PRD_000001`), minimum stock thresholds, and safe deactivation checks.
3. **Склад (`StockPage`, `StockItemDialog`)**:
   - Quantitative stock control, low-stock and out-of-stock indicators, individual IMEI device management (`imei1`, `imei2`, `serial_number`, `condition`, historical cost basis), and direct access to Product & IMEI movement histories.
4. **Закупки (`PurchasePage`, `PurchaseDialog`, `PurchaseDetailsDialog`, `ImeiEntryDialog`)**:
   - Multi-item purchases in USD or TMT with manual exchange rates (`1 USD = X TMT`), optional IMEI intake during purchase, mixed-currency initial and partial supplier payments, purchase cancellation with stock verification, and supplier refund tracking.
5. **Продажи и касса (`SalesPage`, `SaleDetailsDialog`)**:
   - POS search by IMEI (with automatic RU/EN keyboard layout translation), SKU, or product name.
   - Mixed-currency payments (`USD` and `TMT`), change calculation, credit/partial payment sales with customer tracking, historical cost basis snapshot on every `SaleItem`, receipt cancellation, customer debt installment collection, and store-to-customer debt settlement.
6. **Обмен устройств / Trade-in (`ExchangePage`, `ExchangeService`)**:
   - Dedicated device exchange workflow (`DeviceExchange`). Enforces equal-or-higher replacement value (`new_price >= old_price`), blocks duplicate IMEI exchanges, returns the old device to inventory, deducts the replacement device, and records additional payment movements when `new_price > old_price`.
7. **Финансы (`FinancePage`, `FinanceService`)**:
   - Strictly separate `USD` and `TMT` cash register balances and period cash-flow summaries.
   - 4 distinct debt categories:
     1. Customer debts owed to the store.
     2. Store debts owed to suppliers.
     3. Store debts owed to customers (from cancelled sales).
     4. Supplier debts owed to the store (from cancelled purchases).
   - Full Financial Transaction Journal with filters and document drill-down, store operating expense recording (`ExpenseDialog`), and trace-preserving corrective/reversal entries (`CashAdjustmentDialog`).
8. **Отчёты (`ReportsPage`, `ReportService`)**:
   - 7 comprehensive reports calculated from actual database records:
     1. Sales Report (active vs. cancelled separated).
     2. Profit Report (using historical cost basis at the time of sale).
     3. Product Report + complete Product Movement History.
     4. Device (IMEI) Report + continuous IMEI Lifecycle History.
     5. Inventory Report.
     6. Supplier Report.
     7. Customer Report.
   - Export any report to **CSV** (UTF-8 BOM) or **PDF** respecting active filters.
9. **Настройки и Резервное копирование (`SettingsPage`, `SettingsService`, `BackupService`)**:
   - Store profile, default currency & exchange rate, minimum stock threshold, and receipt settings.
   - Transaction-safe SQLite backups via `sqlite3.Connection.backup()`, automatic backup scheduling (`daily` / `on_startup`), retention policy (keeps latest $N$ backups), backup integrity & schema verification, and safe restoration with automatic pre-restore safety backups.

---

## 3. Windows Build, Installation, Update & Backup Guide

### Building the Windows Executable
On a Windows machine with Python 3.11+ installed:

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller

pyinstaller mobilestore.spec --noconfirm
```

The packaged desktop application will be created in `dist\MobileStore\MobileStore.exe`.

### Installation & Directory Layout
- Copy the `dist\MobileStore` folder to a local user-writable directory (for example `C:\MobileStore`).
- On first launch, MobileStore automatically creates:
  - `data\mobilestore.db` — SQLite database.
  - `backups\` — local backup directory.
- You can optionally override the data/backup storage location by setting the `MOBILESTORE_DATA_DIR` environment variable.

### Updating the Application
1. Open **Система → Настройки → Резервное копирование** and click **«Создать резервную копию сейчас»**.
2. Close MobileStore.
3. Replace the application binaries with the new version while keeping the `data\` and `backups\` directories intact.
4. Run `alembic upgrade head` (if updating from source) and launch the application.

### Backup & Recovery Best Practices
- Keep automatic daily backups enabled in **Настройки**.
- Periodically copy backup files from `backups\` to an external USB drive or cloud folder.
- Before restoring any backup, MobileStore automatically verifies the backup file's SQLite integrity and creates a `pre_restore_safety_*.db` backup of the current database.
