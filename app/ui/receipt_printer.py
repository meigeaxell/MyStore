"""Генерация и экспорт в PDF кассовых чеков продаж и Z-отчётов закрытия смены."""
from datetime import datetime
from decimal import Decimal
from html import escape
from pathlib import Path

from PySide6.QtGui import QPageLayout, QPageSize, QTextDocument
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget
from sqlalchemy import select

from app.database.engine import SessionLocal
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.sale_payment import SalePayment
from app.services.sales_service import SalesService
from app.services.settings_service import SettingsService
from app.ui.widgets import money_str


def export_sale_receipt_pdf(sale_id: int, parent: QWidget | None = None) -> bool:
    """Формирует печатную форму кассового чека и сохраняет её в PDF."""
    cfg = SettingsService.get_all()
    store_name = escape(cfg.get("store_name") or "MobileStore")
    store_phone = escape(cfg.get("store_phone") or "")
    store_address = escape(cfg.get("store_address") or "")
    receipt_footer = escape(cfg.get("receipt_footer") or "Satyn alanyňyz üçin sag boluň!")

    with SessionLocal() as session:
        sale = session.get(Sale, sale_id)
        if sale is None:
            if parent:
                QMessageBox.warning(parent, "Çek tapylmady", "Çap etmek üçin çek tapylmady.")
            return False

        items = session.execute(
            select(SaleItem, Product.name, Product.sku)
            .join(Product, SaleItem.product_id == Product.id)
            .where(SaleItem.sale_id == sale.id)
        ).all()

        payments = session.scalars(
            select(SalePayment)
            .where(SalePayment.sale_id == sale.id, SalePayment.payment_type == "payment")
            .order_by(SalePayment.payment_date)
        ).all()

        paid_amt = SalesService.get_sale_paid_amount(session, sale)
        debt_amt = SalesService.get_customer_debt(session, sale)
        receipt_num = sale.receipt_number
        sale_date_str = sale.sale_date.strftime("%d.%m.%Y %H:%M") if sale.sale_date else "—"
        customer = escape(sale.customer_name or "Bölek müşderi")
        if sale.customer_phone:
            customer += f" ({escape(sale.customer_phone)})"
        cur = escape(sale.currency)
        rate_str = f"{Decimal(str(sale.exchange_rate or 1)):,.4f}"
        total_str = money_str(sale.total_amount)
        status_banner = (
            "<p style='color:#E5484D;font-weight:bold;'>ÇEKIŇ STATUSY: ÝATYRYLDY</p>"
            if sale.status == "cancelled"
            else ""
        )

        rows_html = []
        for idx, (s_item, p_name, p_sku) in enumerate(items, start=1):
            line_sum = Decimal(str(s_item.unit_price)) * s_item.quantity - Decimal(str(s_item.discount))
            imei_info = f"<br><span style='color:#667085;font-size:8pt;'>IMEI: {escape(s_item.imei)}</span>" if s_item.imei else ""
            rows_html.append(
                f"<tr>"
                f"<td style='padding:6px;border-bottom:1px solid #E8EBF0;text-align:center;'>{idx}</td>"
                f"<td style='padding:6px;border-bottom:1px solid #E8EBF0;'><b>{escape(p_name)}</b> ({escape(p_sku)}){imei_info}</td>"
                f"<td style='padding:6px;border-bottom:1px solid #E8EBF0;text-align:center;'>{s_item.quantity}</td>"
                f"<td style='padding:6px;border-bottom:1px solid #E8EBF0;text-align:right;'>{money_str(s_item.unit_price)} {cur}</td>"
                f"<td style='padding:6px;border-bottom:1px solid #E8EBF0;text-align:right;'><b>{money_str(line_sum)} {cur}</b></td>"
                f"</tr>"
            )

        pay_lines = [
            f"{money_str(p.amount)} {escape(p.currency)}"
            for p in payments
        ]
        pay_summary = ", ".join(pay_lines) if pay_lines else f"{money_str(paid_amt)} {cur}"

    default_file = str(Path.home() / f"receipt_{receipt_num}.pdf")
    file_path, _ = QFileDialog.getSaveFileName(
        parent,
        f"{receipt_num} çekini PDF-de ýatda sakla",
        default_file,
        "PDF Files (*.pdf)",
    )
    if not file_path:
        return False

    debt_html = (
        f"<p style='color:#F58A2E;font-weight:bold;margin:4px 0;'>Müşderiniň galan bergisi: {money_str(debt_amt)} {cur}</p>"
        if debt_amt > 0
        else "<p style='color:#16A34A;font-weight:bold;margin:4px 0;'>Doly tölendi</p>"
    )

    html = f"""
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family:sans-serif;font-size:9.5pt;color:#1D2939;">
        <div style="text-align:center;border-bottom:2px solid #1B2A41;padding-bottom:8px;margin-bottom:12px;">
            <h2 style="margin:0;color:#1B2A41;">{store_name}</h2>
            <p style="margin:2px 0;color:#667085;font-size:8.5pt;">{store_address}  •  Tel.: {store_phone}</p>
        </div>
        {status_banner}
        <p style="margin:3px 0;"><b>Haryt çeki:</b> {escape(receipt_num)} &nbsp;&nbsp;|&nbsp;&nbsp; <b>Sene:</b> {sale_date_str}</p>
        <p style="margin:3px 0;"><b>Müşderi:</b> {customer} &nbsp;&nbsp;|&nbsp;&nbsp; <b>Walýuta:</b> {cur} (Kurs: {rate_str})</p>
        <table width="100%" cellspacing="0" cellpadding="4" style="border-collapse:collapse;margin-top:10px;">
            <thead>
                <tr style="background:#F2F4F7;">
                    <th style="padding:6px;text-align:center;width:30px;">№</th>
                    <th style="padding:6px;text-align:left;">Haryt / Enjam</th>
                    <th style="padding:6px;text-align:center;width:60px;">Sany</th>
                    <th style="padding:6px;text-align:right;width:110px;">Baha</th>
                    <th style="padding:6px;text-align:right;width:110px;">Jemi</th>
                </tr>
            </thead>
            <tbody>
                {''.join(rows_html)}
            </tbody>
        </table>
        <div style="margin-top:14px;text-align:right;">
            <h3 style="margin:4px 0;color:#1B2A41;">JEMI: {total_str} {cur}</h3>
            <p style="margin:4px 0;">Kabul edildi: {pay_summary}</p>
            {debt_html}
        </div>
        <hr style="border:none;border-top:1px dashed #D0D5DD;margin:16px 0;">
        <p style="text-align:center;color:#667085;font-size:8.5pt;">{receipt_footer}</p>
    </body>
    </html>
    """

    try:
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(file_path)
        printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        printer.setPageOrientation(QPageLayout.Orientation.Portrait)

        doc = QTextDocument()
        doc.setHtml(html)
        doc.print_(printer)

        if parent:
            QMessageBox.information(
                parent,
                "Çek ýatda saklandy",
                f"Çekiň çap görnüşi PDF-de ýatda saklandy:\n{file_path}",
            )
        return True
    except Exception as err:  # noqa: BLE001
        if parent:
            QMessageBox.critical(parent, "Çap ýalňyşlygy", f"PDF ýatda saklap bolmady:\n{err}")
        return False


def export_shift_report_pdf(report_data: dict, parent: QWidget | None = None) -> bool:
    """Сохраняет Z-отчёт закрытия смены и сверки кассы в PDF."""
    cfg = SettingsService.get_all()
    store_name = escape(cfg.get("store_name") or "MobileStore")
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M")

    default_file = str(Path.home() / f"shift_z_report_{datetime.now():%Y%m%d_%H%M}.pdf")
    file_path, _ = QFileDialog.getSaveFileName(
        parent,
        "Smena Z-hasabatyny PDF-de ýatda sakla",
        default_file,
        "PDF Files (*.pdf)",
    )
    if not file_path:
        return False

    html = f"""
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family:sans-serif;font-size:10pt;color:#1D2939;">
        <h2 style="margin-bottom:2px;color:#1B2A41;">{store_name} — Smenany ýapmak Z-Hasabaty</h2>
        <p style="color:#667085;margin-top:0;">Taýýarlanan wagty: {now_str}</p>
        <table width="100%" cellspacing="0" cellpadding="6" style="border-collapse:collapse;margin-top:12px;">
            <thead>
                <tr style="background:#F2F4F7;">
                    <th style="border:1px solid #D0D5DD;text-align:left;">Smena görkezijisi</th>
                    <th style="border:1px solid #D0D5DD;text-align:right;">Kassa USD ($)</th>
                    <th style="border:1px solid #D0D5DD;text-align:right;">Kassa TMT (m.)</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td style="border:1px solid #E8EBF0;">Smena boýunça nagt girdeji (+)</td>
                    <td style="border:1px solid #E8EBF0;text-align:right;">+${money_str(report_data['usd_income'])}</td>
                    <td style="border:1px solid #E8EBF0;text-align:right;">+{money_str(report_data['tmt_income'])} m.</td>
                </tr>
                <tr>
                    <td style="border:1px solid #E8EBF0;">Smena boýunça çykdajy / tölegler (−)</td>
                    <td style="border:1px solid #E8EBF0;text-align:right;">−${money_str(report_data['usd_expense'])}</td>
                    <td style="border:1px solid #E8EBF0;text-align:right;">−{money_str(report_data['tmt_expense'])} m.</td>
                </tr>
                <tr style="font-weight:bold;background:#FAFBFC;">
                    <td style="border:1px solid #E8EBF0;">Programmadaky hasaplanan galyndy</td>
                    <td style="border:1px solid #E8EBF0;text-align:right;">${money_str(report_data['usd_expected'])}</td>
                    <td style="border:1px solid #E8EBF0;text-align:right;">{money_str(report_data['tmt_expected'])} m.</td>
                </tr>
                <tr style="font-weight:bold;">
                    <td style="border:1px solid #E8EBF0;">Kassada hakyky sanalan</td>
                    <td style="border:1px solid #E8EBF0;text-align:right;">${money_str(report_data['usd_actual'])}</td>
                    <td style="border:1px solid #E8EBF0;text-align:right;">{money_str(report_data['tmt_actual'])} m.</td>
                </tr>
                <tr style="font-weight:bold;">
                    <td style="border:1px solid #E8EBF0;">Tapawut (Hakyky − Hasaplanan)</td>
                    <td style="border:1px solid #E8EBF0;text-align:right;">${money_str(report_data['usd_diff'])}</td>
                    <td style="border:1px solid #E8EBF0;text-align:right;">{money_str(report_data['tmt_diff'])} m.</td>
                </tr>
            </tbody>
        </table>
        <p style="margin-top:14px;"><b>Smena satyşlary:</b> {report_data['receipts_count']} çek &nbsp;|&nbsp;
        <b>Smena jemi peýdasy:</b> ${money_str(report_data['profit_usd'])} USD / {money_str(report_data['profit_tmt'])} TMT</p>
    </body>
    </html>
    """

    try:
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(file_path)
        printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        doc = QTextDocument()
        doc.setHtml(html)
        doc.print_(printer)

        if parent:
            QMessageBox.information(parent, "Z-Hasabat ýatda saklandy", f"Smena Z-hasabaty PDF-de ýatda saklandy:\n{file_path}")
        return True
    except Exception as err:  # noqa: BLE001
        if parent:
            QMessageBox.critical(parent, "Ýalňyşlyk", f"Z-hasabaty ýatda saklap bolmady:\n{err}")
        return False
