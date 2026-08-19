
import sys
import os
import shutil
import sqlite3
import hashlib
import secrets
import socket
import uuid
import base64
import json
import csv
from datetime import datetime, timedelta
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QStackedWidget, QFrame, QGridLayout, QTableWidget,
    QTableWidgetItem, QHeaderView, QDialog, QLineEdit, QFormLayout,
    QMessageBox, QDoubleSpinBox, QSpinBox, QDateEdit, QComboBox, QTextEdit,
    QAbstractItemView, QFileDialog, QInputDialog, QCheckBox
)
from PyQt6.QtCore import Qt, QDate, QMarginsF, QSizeF, QObject, QEvent, pyqtSignal
from PyQt6.QtGui import (
    QTextDocument, QPageSize, QPageLayout, QIcon, QPixmap,
    QPainter, QColor, QPen, QFont
)
from PyQt6.QtPrintSupport import QPrinter, QPrintDialog, QPrinterInfo
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature

APP_VENDOR = "AliyanAli"
APP_NAME = "PharmacyPOS"

MOB_ROOT = os.environ.get("PHARMACY_POS_ROOT", r"D:\MOB")

APP_DIR = os.path.join(MOB_ROOT, "App")
ASSETS_DIR = os.path.join(MOB_ROOT, "Assets")
CONFIG_DIR = os.path.join(MOB_ROOT, "Config")
DATABASE_DIR = os.path.join(MOB_ROOT, "Database")
BACKUP_DIR = os.path.join(MOB_ROOT, "Backup")
REPORTS_DIR = os.path.join(MOB_ROOT, "Reports")
DRIVERS_DIR = os.path.join(MOB_ROOT, "Drivers")
UPDATES_DIR = os.path.join(MOB_ROOT, "Updates")
SUPPORT_DIR = os.path.join(MOB_ROOT, "Support")
TEMP_DIR = os.path.join(MOB_ROOT, "Temp")

DB_NAME = os.path.join(DATABASE_DIR, "pharmacy.db")
SETTINGS_JSON = os.path.join(CONFIG_DIR, "settings.json")
LICENSE_FILE = os.path.join(CONFIG_DIR, "license.dat")

LOGO_FILE = os.path.join(ASSETS_DIR, "logo.png")
APP_ICON_FILE = os.path.join(ASSETS_DIR, "pharmacy.ico")
RECEIPT_LOGO_FILE = os.path.join(ASSETS_DIR, "receipt_logo.png")

CURRENT_RECEIPT_USER = "Admin"


def ensure_mob_structure():
    folders = [
        APP_DIR, ASSETS_DIR, CONFIG_DIR, DATABASE_DIR,
        BACKUP_DIR, REPORTS_DIR, DRIVERS_DIR, UPDATES_DIR,
        SUPPORT_DIR, TEMP_DIR
    ]

    try:
        for folder in folders:
            os.makedirs(folder, exist_ok=True)
        return True, ""
    except Exception as error:
        return False, str(error)


def legacy_data_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_VENDOR, APP_NAME)


def migrate_legacy_database_to_mob():
    source = os.path.join(legacy_data_dir(), "pharmacy.db")
    target = DB_NAME

    try:
        if not os.path.exists(source):
            return

        should_copy = not os.path.exists(target)

        if os.path.exists(target):
            try:
                should_copy = os.path.getmtime(source) > os.path.getmtime(target)
            except Exception:
                should_copy = False

        if not should_copy:
            return

        if os.path.exists(target):
            backup_name = os.path.join(
                BACKUP_DIR,
                "pre_v20_migration_"
                + datetime.now().strftime("%Y%m%d_%H%M%S")
                + ".db"
            )
            shutil.copy2(target, backup_name)

        shutil.copy2(source, target)

    except Exception:
        pass


def load_settings_json():
    try:
        if not os.path.exists(SETTINGS_JSON):
            return {}

        raw = Path(SETTINGS_JSON).read_text(encoding="utf-8").strip()

        if not raw:
            return {}

        data = json.loads(raw)
        return data if isinstance(data, dict) else {}

    except Exception:
        return {}


def save_settings_json(data):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        temp_file = SETTINGS_JSON + ".tmp"

        Path(temp_file).write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

        os.replace(temp_file, SETTINGS_JSON)

    except Exception:
        pass


def read_license_file():
    try:
        if not os.path.exists(LICENSE_FILE):
            return ""

        return Path(LICENSE_FILE).read_text(encoding="utf-8").strip()

    except Exception:
        return ""


def write_license_file(license_key):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        temp_file = LICENSE_FILE + ".tmp"

        Path(temp_file).write_text(
            str(license_key).strip(),
            encoding="utf-8"
        )

        os.replace(temp_file, LICENSE_FILE)

        if sys.platform.startswith("win"):
            try:
                import ctypes
                ctypes.windll.kernel32.SetFileAttributesW(
                    LICENSE_FILE,
                    0x02
                )
            except Exception:
                pass

        return True

    except Exception:
        return False


def sync_config_files_from_database():
    if not os.path.exists(DB_NAME):
        return

    try:
        con = sqlite3.connect(DB_NAME)
        rows = con.execute(
            "SELECT key, value FROM settings"
        ).fetchall()
        con.close()

        db_settings = {
            str(key): ("" if value is None else str(value))
            for key, value in rows
        }

        json_keys = [
            "pharmacy_name",
            "address",
            "phone",
            "receipt_footer",
            "low_stock_limit",
            "setup_completed"
        ]

        json_data = load_settings_json()

        for key in json_keys:
            if key not in json_data and key in db_settings:
                json_data[key] = db_settings[key]

        save_settings_json(json_data)

        if not read_license_file():
            old_license = db_settings.get("license_key", "").strip()

            if old_license:
                write_license_file(old_license)

    except Exception:
        pass

LICENSE_PUBLIC_KEY_PEM = r"""-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAtZjp33kWTrwhOKUxr/SNB9cerUoLdIThR+FrD6CwL20=
-----END PUBLIC KEY-----
"""


def _b64url_decode(value):
    value = value.encode("ascii")
    value += b"=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value)


def _b64url_encode(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def get_machine_id():
    parts = []

    if sys.platform.startswith("win"):
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography"
            )
            machine_guid, _ = winreg.QueryValueEx(key, "MachineGuid")
            winreg.CloseKey(key)
            if machine_guid:
                parts.append(str(machine_guid))
        except Exception:
            pass

    if not parts:
        try:
            parts.append(socket.gethostname())
        except Exception:
            pass
        try:
            parts.append(str(uuid.getnode()))
        except Exception:
            pass

    raw = "|".join(parts) or "UNKNOWN-MACHINE"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()[:24]
    return "-".join(digest[i:i + 4] for i in range(0, len(digest), 4))


def verify_license_key(license_key):
    try:
        if not license_key or "." not in license_key:
            return False, "Not Registered", None

        payload_part, signature_part = license_key.strip().split(".", 1)
        payload_bytes = _b64url_decode(payload_part)
        signature_bytes = _b64url_decode(signature_part)

        public_key = serialization.load_pem_public_key(
            LICENSE_PUBLIC_KEY_PEM.encode("utf-8")
        )
        public_key.verify(signature_bytes, payload_bytes)

        payload = json.loads(payload_bytes.decode("utf-8"))

        if payload.get("machine_id") != get_machine_id():
            return False, "License is for another computer", payload

        expiry = payload.get("expires_on", "")

        if expiry and expiry != "PERPETUAL":
            try:
                expiry_date = datetime.strptime(expiry, "%Y-%m-%d").date()
                if datetime.now().date() > expiry_date:
                    return False, f"License expired on {expiry}", payload
            except ValueError:
                return False, "Invalid license expiry date", payload

        if payload.get("status", "ACTIVE") != "ACTIVE":
            return False, "License is not active", payload

        return True, "Active", payload

    except InvalidSignature:
        return False, "Invalid License Key", None
    except Exception:
        return False, "Invalid License Key", None


def get_license_status():
    license_key = read_license_file()

    if not license_key:
        license_key = get_setting("license_key", "")

        if license_key:
            write_license_file(license_key)

    return verify_license_key(license_key)


def save_activated_license(license_key, payload):
    if not write_license_file(license_key):
        raise RuntimeError(
            "Could not save D:\\MOB\\Config\\license.dat"
        )

    set_setting("license_key", license_key)
    set_setting("license_pharmacy_name", payload.get("pharmacy_name", ""))
    set_setting("license_owner_name", payload.get("owner_name", ""))
    set_setting("license_phone", payload.get("phone", ""))
    set_setting("license_city", payload.get("city", ""))
    set_setting("license_expires_on", payload.get("expires_on", ""))

    if payload.get("pharmacy_name"):
        set_setting("pharmacy_name", payload["pharmacy_name"])

    if payload.get("phone"):
        set_setting("phone", payload["phone"])


def migrate_old_local_database_if_needed():
    migrate_legacy_database_to_mob()


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def generate_invoice(prefix="INV"):
    return prefix + "-" + datetime.now().strftime("%Y%m%d-%H%M%S%f")[:-3]


def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)

    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        120000
    ).hex()

    return salt, password_hash


def verify_password(password, salt, stored_hash):
    _, candidate = hash_password(password, salt)
    return secrets.compare_digest(candidate, stored_hash)


JSON_SETTING_KEYS = {
    "pharmacy_name",
    "address",
    "phone",
    "receipt_footer",
    "low_stock_limit",
    "setup_completed",
    "receipt_paper_width",
    "default_tax_rate"
}


def get_setting(key, default=""):
    if key in JSON_SETTING_KEYS:
        data = load_settings_json()

        if key in data:
            value = data.get(key)
            return default if value is None else str(value)

    try:
        con = sqlite3.connect(DB_NAME)
        row = con.execute(
            "SELECT value FROM settings WHERE key = ?",
            (key,)
        ).fetchone()
        con.close()

        if row is None:
            return default

        return row[0] if row[0] is not None else default

    except Exception:
        return default


def set_setting(key, value):
    value = str(value)

    con = sqlite3.connect(DB_NAME)
    con.execute("""
        INSERT INTO settings (key, value)
        VALUES (?, ?)
        ON CONFLICT(key)
        DO UPDATE SET value = excluded.value
    """, (key, value))
    con.commit()
    con.close()

    if key in JSON_SETTING_KEYS:
        data = load_settings_json()
        data[key] = value
        save_settings_json(data)


def is_first_run_setup_required():
    return get_setting("setup_completed", "0") != "1"


class EnterNavigationFilter(QObject):
    """
    Makes Enter behave like Tab across normal data-entry forms.
    Important controls keep their own Enter behavior:
    - POS search uses Enter to search / scan
    - Tables use Enter to activate selected row
    - Buttons use Enter to click
    - QTextEdit keeps multiline behavior
    """
    def eventFilter(self, obj, event):
        if event.type() != QEvent.Type.KeyPress:
            return False

        if event.key() not in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter
        ):
            return False

        if isinstance(obj, QTextEdit):
            return False

        if isinstance(obj, QPushButton):
            return False

        if isinstance(obj, QTableWidget):
            return False

        # POS controls keep their own Enter behavior.
        if obj.objectName() in ("posSearchInput", "posCashReceivedLine"):
            return False

        if isinstance(
            obj,
            (
                QLineEdit,
                QComboBox,
                QSpinBox,
                QDoubleSpinBox,
                QDateEdit
            )
        ):
            obj.focusNextChild()
            return True

        return False


def setup_table(table):
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.verticalHeader().setVisible(False)
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)


def connect_enter_to_next(widgets):
    """
    Makes Enter work like Tab in data-entry forms.
    For QLineEdit, pressing Enter moves to the next field.
    """
    for index, widget in enumerate(widgets[:-1]):
        next_widget = widgets[index + 1]

        if isinstance(widget, QLineEdit):
            try:
                widget.returnPressed.connect(next_widget.setFocus)
            except Exception:
                pass


def build_receipt_html(invoice):
    con = sqlite3.connect(DB_NAME)
    con.row_factory = sqlite3.Row

    sales = con.execute("""
        SELECT medicine, quantity, total, created_at
        FROM sales
        WHERE invoice = ?
        ORDER BY id
    """, (invoice,)).fetchall()

    payment = con.execute("""
        SELECT subtotal, received, change_amount, payment_method, created_at,
               COALESCE(discount, 0) AS discount,
               COALESCE(tax, 0) AS tax,
               customer_id
        FROM payments
        WHERE invoice = ?
        ORDER BY id DESC
        LIMIT 1
    """, (invoice,)).fetchone()

    customer_name = "Walk-in"
    if payment and payment["customer_id"]:
        customer_row = con.execute(
            "SELECT name FROM customers WHERE id = ?",
            (payment["customer_id"],)
        ).fetchone()
        if customer_row and customer_row[0]:
            customer_name = customer_row[0]

    returned = con.execute("""
        SELECT COALESCE(SUM(refund_amount), 0)
        FROM sales_returns
        WHERE invoice = ?
    """, (invoice,)).fetchone()[0]

    con.close()

    if not sales:
        return None, None

    pharmacy_name = get_setting("pharmacy_name", "PHARMACY POS")
    address = get_setting("address", "")

    receipt_logo_html = ""

    if os.path.exists(RECEIPT_LOGO_FILE):
        logo_url = Path(RECEIPT_LOGO_FILE).resolve().as_uri()
        receipt_logo_html = (
            f'<div class="center">'
            f'<img src="{logo_url}" style="max-width:50mm; max-height:16mm;">'
            f'</div>'
        )
    phone = get_setting("phone", "")
    footer = get_setting("receipt_footer", "Thank you for your purchase.")

    created_at = sales[0]["created_at"] or now_text()
    try:
        dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
        display_date = dt.strftime("%d-%m-%Y %I:%M:%S %p")
    except Exception:
        display_date = created_at

    gross_total = sum(float(row["total"] or 0) for row in sales)
    total_qty = sum(int(row["quantity"] or 0) for row in sales)

    received = float(payment["received"] or 0) if payment else gross_total
    change = float(payment["change_amount"] or 0) if payment else 0
    payment_method = payment["payment_method"] if payment else "Cash"
    discount = float(payment["discount"] or 0) if payment else 0
    tax = float(payment["tax"] or 0) if payment else 0
    net_after_returns = max(0, gross_total - discount + tax - float(returned or 0))

    rows_html = ""
    for idx, row in enumerate(sales, start=1):
        qty = int(row["quantity"] or 0)
        line_total = float(row["total"] or 0)
        rate = (line_total / qty) if qty else 0
        rows_html += f"""
        <tr>
            <td style="width:7%">{idx}</td>
            <td style="width:48%">{row['medicine']}</td>
            <td style="width:10%; text-align:center">{qty}</td>
            <td style="width:15%; text-align:right">{rate:,.0f}</td>
            <td style="width:20%; text-align:right">{line_total:,.2f}</td>
        </tr>
        """

    contact_line = ""
    if address:
        contact_line += f"<div>{address}</div>"
    if phone:
        contact_line += f"<div>Ph: {phone}</div>"

    html = f"""
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{
                font-family: Arial, Helvetica, sans-serif;
                font-size: 9pt;
                color: #000;
                margin: 0;
                padding: 0;
            }}
            .center {{ text-align: center; }}
            .title {{
                font-size: 18pt;
                font-weight: 900;
                margin-bottom: 2px;
            }}
            .small {{ font-size: 8pt; }}
            .line {{
                border-top: 1px solid #000;
                margin: 5px 0;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                font-size: 8.5pt;
            }}
            th {{
                background: #000;
                color: #fff;
                padding: 3px 2px;
                font-weight: 700;
            }}
            td {{
                padding: 3px 2px;
                border-bottom: 1px dotted #888;
                vertical-align: top;
            }}
            .totals {{
                width: 100%;
                margin-top: 7px;
                font-size: 9pt;
            }}
            .totals td {{
                border: 0;
                padding: 2px;
            }}
            .bold {{ font-weight: 700; }}
            .dev {{
                margin-top: 9px;
                font-size: 7.5pt;
                text-align: center;
            }}
        </style>
    </head>
    <body>
        {receipt_logo_html}
        <div class="center title">{pharmacy_name}</div>
        <div class="center small">{contact_line}</div>

        <div class="line"></div>

        <div><b>Bill #:</b> {invoice}</div>
        <div><b>Counter:</b> {CURRENT_RECEIPT_USER}</div>
        <div><b>Date & Time:</b> {display_date}</div>
        <div><b>Customer:</b> {customer_name}</div>

        <div class="line"></div>

        <table>
            <tr>
                <th>#</th>
                <th>DESCRIPTION</th>
                <th>QTY</th>
                <th>RATE</th>
                <th>TOTAL</th>
            </tr>
            {rows_html}
        </table>

        <table class="totals">
            <tr>
                <td></td>
                <td class="bold">Net Total:</td>
                <td style="text-align:right">{gross_total:,.2f}</td>
            </tr>
            <tr>
                <td></td>
                <td class="bold">Discount:</td>
                <td style="text-align:right">{discount:,.2f}</td>
            </tr>
            <tr>
                <td></td>
                <td class="bold">Tax:</td>
                <td style="text-align:right">{tax:,.2f}</td>
            </tr>
            <tr>
                <td></td>
                <td class="bold">Returned:</td>
                <td style="text-align:right">{float(returned or 0):,.2f}</td>
            </tr>
            <tr>
                <td></td>
                <td class="bold">Payable:</td>
                <td style="text-align:right">PKR {net_after_returns:,.2f}</td>
            </tr>
            <tr><td colspan="3"><div class="line"></div></td></tr>
            <tr>
                <td></td>
                <td class="bold">Received: {payment_method}</td>
                <td style="text-align:right">{received:,.2f}</td>
            </tr>
            <tr>
                <td></td>
                <td class="bold">Change:</td>
                <td style="text-align:right">{change:,.2f}</td>
            </tr>
        </table>

        <div class="line"></div>
        <div class="center"><b>Total Quantity:</b> {total_qty}</div>
        <div class="line"></div>

        <div class="center">{footer}</div>
        <div class="dev">POS Software by Wabwar | 03166965457</div>
    </body>
    </html>
    """

    return html, {
        "invoice": invoice,
        "gross_total": gross_total,
        "returned": float(returned or 0),
        "discount": discount,
        "tax": tax,
        "customer": customer_name,
        "payable": net_after_returns,
        "received": received,
        "change": change,
        "payment_method": payment_method,
        "total_qty": total_qty
    }


def print_receipt_invoice(parent, invoice):
    html, _ = build_receipt_html(invoice)

    if not html:
        QMessageBox.warning(parent, "Not Found", "Invoice was not found.")
        return

    document = QTextDocument()
    document.setHtml(html)

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)

    # Thermal receipt width can be set to 58mm or 80mm from Settings.
    try:
        paper_width = int(float(get_setting("receipt_paper_width", "80") or 80))
    except Exception:
        paper_width = 80
    if paper_width not in (58, 80):
        paper_width = 80

    page_size = QPageSize(
        QPageSize.PageSizeId.Custom,
        QSizeF(paper_width, 297),
        QPageSize.Unit.Millimeter,
        f"{paper_width}mm Receipt"
    )
    printer.setPageSize(page_size)
    margin = 2 if paper_width == 58 else 3
    printer.setPageMargins(
        QMarginsF(margin, 2, margin, 2),
        QPageLayout.Unit.Millimeter
    )

    dialog = QPrintDialog(printer, parent)
    dialog.setWindowTitle("Print Receipt")

    if dialog.exec() == QDialog.DialogCode.Accepted:
        document.print(printer)


def init_database():
    con = sqlite3.connect(DB_NAME)

    con.execute("""
        CREATE TABLE IF NOT EXISTS medicines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            generic_name TEXT,
            barcode TEXT,
            category TEXT,
            purchase_price REAL DEFAULT 0,
            sale_price REAL DEFAULT 0,
            stock INTEGER DEFAULT 0,
            expiry_date TEXT,
            created_at TEXT
        )
    """)

    # Inventory Control v2.3 fields - added safely for existing databases.
    medicine_columns = {
        row[1] for row in con.execute("PRAGMA table_info(medicines)").fetchall()
    }
    inventory_columns = {
        "whole_sale_price": "REAL DEFAULT 0",
        "tax_rate": "REAL DEFAULT 0",
        "scheme": "TEXT",
        "reorder_level": "INTEGER DEFAULT 0",
        "location": "TEXT",
        "batch_number": "TEXT"
    }
    for column_name, column_type in inventory_columns.items():
        if column_name not in medicine_columns:
            con.execute(
                f"ALTER TABLE medicines ADD COLUMN {column_name} {column_type}"
            )

    con.execute("""
        CREATE TABLE IF NOT EXISTS suppliers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT,
            company TEXT,
            address TEXT,
            created_at TEXT
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS medicine_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            medicine_id INTEGER NOT NULL,
            supplier_id INTEGER,
            batch_number TEXT NOT NULL,
            expiry_date TEXT,
            purchase_price REAL DEFAULT 0,
            sale_price REAL DEFAULT 0,
            quantity_received INTEGER DEFAULT 0,
            quantity_available INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_number TEXT NOT NULL,
            supplier_id INTEGER,
            medicine_id INTEGER NOT NULL,
            batch_number TEXT,
            expiry_date TEXT,
            quantity INTEGER DEFAULT 0,
            purchase_price REAL DEFAULT 0,
            sale_price REAL DEFAULT 0,
            total REAL DEFAULT 0,
            created_at TEXT
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice TEXT,
            medicine TEXT,
            quantity INTEGER,
            total REAL,
            created_at TEXT
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice TEXT,
            subtotal REAL DEFAULT 0,
            received REAL DEFAULT 0,
            change_amount REAL DEFAULT 0,
            payment_method TEXT DEFAULT 'Cash',
            created_at TEXT
        )
    """)

    payment_columns = {row[1] for row in con.execute("PRAGMA table_info(payments)").fetchall()}
    for column_name, column_type in {
        "customer_id": "INTEGER",
        "discount": "REAL DEFAULT 0",
        "tax": "REAL DEFAULT 0",
        "total_due": "REAL DEFAULT 0"
    }.items():
        if column_name not in payment_columns:
            con.execute(f"ALTER TABLE payments ADD COLUMN {column_name} {column_type}")

    con.execute("""
        CREATE TABLE IF NOT EXISTS sale_batch_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice TEXT NOT NULL,
            medicine_id INTEGER NOT NULL,
            batch_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            created_at TEXT
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS sales_returns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            return_number TEXT NOT NULL,
            invoice TEXT NOT NULL,
            medicine_id INTEGER,
            medicine TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            refund_amount REAL DEFAULT 0,
            reason TEXT,
            created_at TEXT
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            tax_rate REAL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT,
            address TEXT,
            created_at TEXT
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            description TEXT,
            amount REAL NOT NULL DEFAULT 0,
            expense_date TEXT NOT NULL,
            created_at TEXT
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            full_name TEXT,
            role TEXT NOT NULL DEFAULT 'Cashier',
            password_salt TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT
        )
    """)

    default_settings = {
        "pharmacy_name": "PHARMACY POS",
        "address": "",
        "phone": "",
        "receipt_footer": "Thank you for your purchase.",
        "low_stock_limit": "10",
        "setup_completed": "0",
        "license_key": "",
        "license_pharmacy_name": "",
        "license_owner_name": "",
        "license_phone": "",
        "license_city": "",
        "license_expires_on": "",
        "receipt_paper_width": "80",
        "default_tax_rate": "0"
    }

    for key, value in default_settings.items():
        con.execute("""
            INSERT OR IGNORE INTO settings (key, value)
            VALUES (?, ?)
        """, (key, value))

    # Existing v1.x pharmacy databases already contain real pharmacy data.
    # Mark them configured automatically, so upgrades do not force setup again.
    existing_name = con.execute("""
        SELECT value FROM settings WHERE key = 'pharmacy_name'
    """).fetchone()

    existing_completed = con.execute("""
        SELECT value FROM settings WHERE key = 'setup_completed'
    """).fetchone()

    if (
        existing_name
        and existing_name[0]
        and existing_name[0] != "PHARMACY POS"
        and existing_completed
        and existing_completed[0] == "0"
    ):
        con.execute("""
            UPDATE settings
            SET value = '1'
            WHERE key = 'setup_completed'
        """)

    user_count = con.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    if user_count == 0:
        salt, password_hash = hash_password("admin123")
        con.execute("""
            INSERT INTO users (
                username, full_name, role,
                password_salt, password_hash,
                active, created_at
            )
            VALUES (?, ?, ?, ?, ?, 1, ?)
        """, (
            "admin",
            "Administrator",
            "Admin",
            salt,
            password_hash,
            now_text()
        ))

    # Legacy stock reconciliation
    medicines = con.execute("""
        SELECT id, stock, purchase_price, sale_price, expiry_date
        FROM medicines
    """).fetchall()

    for medicine in medicines:
        medicine_id = medicine[0]
        master_stock = int(medicine[1] or 0)
        purchase_price = float(medicine[2] or 0)
        sale_price = float(medicine[3] or 0)
        expiry_date = medicine[4]

        batch_stock = con.execute("""
            SELECT COALESCE(SUM(quantity_available), 0)
            FROM medicine_batches
            WHERE medicine_id = ?
        """, (medicine_id,)).fetchone()[0]

        missing = master_stock - int(batch_stock or 0)

        if missing > 0:
            legacy = con.execute("""
                SELECT id FROM medicine_batches
                WHERE medicine_id = ? AND batch_number = 'LEGACY-OPENING'
            """, (medicine_id,)).fetchone()

            if legacy:
                con.execute("""
                    UPDATE medicine_batches
                    SET quantity_received = quantity_received + ?,
                        quantity_available = quantity_available + ?
                    WHERE id = ?
                """, (missing, missing, legacy[0]))
            else:
                con.execute("""
                    INSERT INTO medicine_batches (
                        medicine_id, supplier_id, batch_number, expiry_date,
                        purchase_price, sale_price, quantity_received,
                        quantity_available, created_at
                    )
                    VALUES (?, NULL, 'LEGACY-OPENING', ?, ?, ?, ?, ?, ?)
                """, (
                    medicine_id, expiry_date, purchase_price, sale_price,
                    missing, missing, now_text()
                ))

    con.commit()
    con.close()





class StatCard(QFrame):
    """Small report KPI card used by the Admin/Business Reports page."""
    def __init__(self, title, value="Rs. 0", subtitle=""):
        super().__init__()
        self.setObjectName("reportStatCard")
        self.setMinimumHeight(88)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(3)

        title_label = QLabel(title)
        title_label.setObjectName("reportStatTitle")

        self.value_label = QLabel(value)
        self.value_label.setObjectName("reportStatValue")

        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("reportStatSubtitle")

        layout.addWidget(title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(subtitle_label)

class SalesChartWidget(QWidget):
    """7-day Sales vs Purchase bar chart with no external chart dependency."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.labels = []
        self.values = []
        self.purchase_values = []
        self.setMinimumHeight(275)
        self.setObjectName("salesChart")

    def set_data(self, labels, values, purchase_values=None):
        self.labels = list(labels or [])
        self.values = [float(v or 0) for v in (values or [])]
        self.purchase_values = [float(v or 0) for v in (purchase_values or [])]
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect().adjusted(12, 8, -12, -10)
        painter.fillRect(rect, QColor("#ffffff"))

        title_font = QFont()
        title_font.setPointSize(10)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor("#334155"))
        painter.drawText(rect.left() + 10, rect.top() + 18, "Sales / Purchase - Last 7 Days")

        # Legend
        painter.setBrush(QColor("#2ec4b6"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(rect.left() + 220, rect.top() + 8, 12, 8)
        painter.setPen(QColor("#64748b"))
        painter.drawText(rect.left() + 237, rect.top() + 18, "Sales")
        painter.setBrush(QColor("#94a3b8"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(rect.left() + 280, rect.top() + 8, 12, 8)
        painter.setPen(QColor("#64748b"))
        painter.drawText(rect.left() + 297, rect.top() + 18, "Purchase")

        chart_left = rect.left() + 58
        chart_top = rect.top() + 38
        chart_right = rect.right() - 12
        chart_bottom = rect.bottom() - 34

        if chart_right <= chart_left or chart_bottom <= chart_top:
            return

        sales = self.values if self.values else [0] * 7
        purchases = self.purchase_values if self.purchase_values else [0] * len(sales)
        labels = self.labels if self.labels else ["-"] * len(sales)

        max_value = max(sales + purchases + [1])

        grid_pen = QPen(QColor("#e5e7eb"))
        painter.setPen(grid_pen)
        small_font = QFont()
        small_font.setPointSize(7)
        painter.setFont(small_font)

        for i in range(5):
            y = chart_top + (chart_bottom - chart_top) * i / 4
            painter.drawLine(int(chart_left), int(y), int(chart_right), int(y))
            value = max_value * (4 - i) / 4
            painter.setPen(QColor("#64748b"))
            painter.drawText(rect.left() + 2, int(y) + 3, f"{value:,.0f}")
            painter.setPen(grid_pen)

        count = max(1, len(sales))
        group_w = (chart_right - chart_left) / count
        bar_w = max(7, min(22, group_w * 0.24))

        for i in range(count):
            center = chart_left + group_w * i + group_w / 2

            sale_h = (sales[i] / max_value) * (chart_bottom - chart_top)
            purchase_val = purchases[i] if i < len(purchases) else 0
            purchase_h = (purchase_val / max_value) * (chart_bottom - chart_top)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#2ec4b6"))
            painter.drawRect(
                int(center - bar_w - 2),
                int(chart_bottom - sale_h),
                int(bar_w),
                int(sale_h)
            )

            painter.setBrush(QColor("#94a3b8"))
            painter.drawRect(
                int(center + 2),
                int(chart_bottom - purchase_h),
                int(bar_w),
                int(purchase_h)
            )

            painter.setPen(QColor("#64748b"))
            label = labels[i] if i < len(labels) else ""
            painter.drawText(
                int(center - group_w / 2), chart_bottom + 10,
                int(group_w), 18,
                Qt.AlignmentFlag.AlignCenter, label
            )

        painter.setPen(QColor("#64748b"))
        total_sales = sum(sales)
        total_purchase = sum(purchases)
        painter.drawText(
            chart_right - 260, rect.top() + 18, 250, 18,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            f"Sales Rs. {total_sales:,.0f}  |  Purchase Rs. {total_purchase:,.0f}"
        )


class DashboardMetricCard(QFrame):
    """Clickable reference-style dashboard summary tile."""
    clicked = pyqtSignal()

    def __init__(self, title, value="0", color="#0ea56b", subtitle=""):
        super().__init__()
        self.setObjectName("dashboardMetricCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            "QFrame#dashboardMetricCard {"
            f"background: {color}; border: none; border-radius: 3px;"
            "}"
        )
        self.setMinimumHeight(86)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(2)

        self.value_label = QLabel(value)
        self.value_label.setObjectName("dashboardMetricValue")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)

        self.title_label = QLabel(title.upper())
        self.title_label.setObjectName("dashboardMetricTitle")

        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("dashboardMetricSubtitle")

        layout.addWidget(self.value_label)
        layout.addStretch()
        layout.addWidget(self.title_label)
        if subtitle:
            layout.addWidget(self.subtitle_label)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class AddCategoryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Category Management")
        self.resize(620, 470)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)

        title = QLabel("Medicine Categories")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)

        form = QHBoxLayout()
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Category name")
        self.tax_input = QDoubleSpinBox()
        self.tax_input.setRange(0, 100)
        self.tax_input.setDecimals(2)
        self.tax_input.setSuffix(" %")
        save = QPushButton("Save Category")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.save_category)
        form.addWidget(self.name_input, 2)
        form.addWidget(self.tax_input, 1)
        form.addWidget(save)
        layout.addLayout(form)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["ID", "Category", "Tax %", "Status"])
        setup_table(self.table)
        layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        delete = QPushButton("Delete Selected")
        delete.setObjectName("dangerButton")
        delete.clicked.connect(self.delete_selected)
        close = QPushButton("Close")
        close.setObjectName("secondaryButton")
        close.clicked.connect(self.accept)
        actions.addStretch()
        actions.addWidget(delete)
        actions.addWidget(close)
        layout.addLayout(actions)

        self.setStyleSheet(DIALOG_STYLE)
        self.load_categories()
        self.name_input.setFocus()

    def load_categories(self):
        con = sqlite3.connect(DB_NAME)
        rows = con.execute(
            "SELECT id, name, tax_rate, active FROM categories ORDER BY name COLLATE NOCASE"
        ).fetchall()
        con.close()
        self.table.setRowCount(0)
        for row in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            vals = [row[0], row[1], f"{float(row[2] or 0):.2f}", "Active" if row[3] else "Inactive"]
            for c, val in enumerate(vals):
                self.table.setItem(r, c, QTableWidgetItem(str(val)))

    def save_category(self):
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Required", "Category name is required.")
            return
        con = sqlite3.connect(DB_NAME)
        try:
            con.execute(
                "INSERT INTO categories(name, tax_rate, active, created_at) VALUES(?, ?, 1, ?)",
                (name, self.tax_input.value(), now_text())
            )
            con.commit()
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, "Duplicate", "This category already exists.")
            con.close()
            return
        con.close()
        self.name_input.clear()
        self.tax_input.setValue(0)
        self.load_categories()

    def delete_selected(self):
        row = self.table.currentRow()
        if row < 0:
            return
        category_id = int(self.table.item(row, 0).text())
        category_name = self.table.item(row, 1).text()
        con = sqlite3.connect(DB_NAME)
        used = con.execute(
            "SELECT COUNT(*) FROM medicines WHERE category = ?", (category_name,)
        ).fetchone()[0]
        if used:
            con.close()
            QMessageBox.warning(self, "Category In Use", "This category is already assigned to medicines and cannot be deleted.")
            return
        con.execute("DELETE FROM categories WHERE id = ?", (category_id,))
        con.commit()
        con.close()
        self.load_categories()


class AddMedicineDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Medicine")
        self.setFixedWidth(500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(18)

        title = QLabel("Add New Medicine")
        title.setObjectName("dialogTitle")
        subtitle = QLabel("Enter medicine details below.")
        subtitle.setObjectName("dialogSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        form = QFormLayout()
        form.setSpacing(14)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. Panadol 500mg")
        self.generic_input = QLineEdit()
        self.generic_input.setPlaceholderText("e.g. Paracetamol")
        self.barcode_input = QLineEdit()
        self.barcode_input.setPlaceholderText("Scan or enter barcode")
        self.category_input = QLineEdit()
        self.category_input.setPlaceholderText("e.g. Pain Killer")

        self.purchase_input = QDoubleSpinBox()
        self.purchase_input.setRange(0, 99999999)
        self.purchase_input.setDecimals(2)
        self.purchase_input.setPrefix("Rs. ")

        self.sale_input = QDoubleSpinBox()
        self.sale_input.setRange(0, 99999999)
        self.sale_input.setDecimals(2)
        self.sale_input.setPrefix("Rs. ")

        self.stock_input = QSpinBox()
        self.stock_input.setRange(0, 9999999)

        self.expiry_input = QDateEdit()
        self.expiry_input.setCalendarPopup(True)
        self.expiry_input.setDate(QDate.currentDate().addYears(1))
        self.expiry_input.setDisplayFormat("dd-MM-yyyy")

        form.addRow("Medicine Name *", self.name_input)
        form.addRow("Generic Name", self.generic_input)
        form.addRow("Barcode", self.barcode_input)
        form.addRow("Category", self.category_input)
        form.addRow("Purchase Price", self.purchase_input)
        form.addRow("Sale Price", self.sale_input)
        form.addRow("Opening Stock", self.stock_input)
        form.addRow("Expiry Date", self.expiry_input)

        layout.addLayout(form)

        connect_enter_to_next([
            self.name_input,
            self.generic_input,
            self.barcode_input,
            self.category_input
        ])

        buttons = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.setObjectName("secondaryButton")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save Medicine")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.save_medicine)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

        self.setStyleSheet(DIALOG_STYLE)

    def save_medicine(self):
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Required", "Medicine name is required.")
            return

        barcode = self.barcode_input.text().strip()
        con = sqlite3.connect(DB_NAME)

        if barcode:
            existing = con.execute(
                "SELECT id FROM medicines WHERE barcode = ?", (barcode,)
            ).fetchone()
            if existing:
                con.close()
                QMessageBox.warning(self, "Duplicate Barcode", "This barcode already exists.")
                return

        stock = self.stock_input.value()
        expiry = self.expiry_input.date().toString("yyyy-MM-dd")

        cursor = con.execute("""
            INSERT INTO medicines (
                name, generic_name, barcode, category, purchase_price,
                sale_price, stock, expiry_date, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            name,
            self.generic_input.text().strip(),
            barcode,
            self.category_input.text().strip(),
            self.purchase_input.value(),
            self.sale_input.value(),
            stock,
            expiry,
            now_text()
        ))

        medicine_id = cursor.lastrowid

        if stock > 0:
            con.execute("""
                INSERT INTO medicine_batches (
                    medicine_id, supplier_id, batch_number, expiry_date,
                    purchase_price, sale_price, quantity_received,
                    quantity_available, created_at
                )
                VALUES (?, NULL, 'OPENING', ?, ?, ?, ?, ?, ?)
            """, (
                medicine_id, expiry, self.purchase_input.value(),
                self.sale_input.value(), stock, stock, now_text()
            ))

        con.commit()
        con.close()
        QMessageBox.information(self, "Success", "Medicine saved successfully.")
        self.accept()


class AddSupplierDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Supplier")
        self.setFixedWidth(480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(16)

        title = QLabel("Add Supplier")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(14)

        self.name_input = QLineEdit()
        self.company_input = QLineEdit()
        self.phone_input = QLineEdit()
        self.address_input = QLineEdit()

        form.addRow("Supplier Name *", self.name_input)
        form.addRow("Company", self.company_input)
        form.addRow("Phone", self.phone_input)
        form.addRow("Address", self.address_input)
        layout.addLayout(form)

        connect_enter_to_next([
            self.name_input,
            self.company_input,
            self.phone_input,
            self.address_input
        ])


        buttons = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.setObjectName("secondaryButton")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save Supplier")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.save_supplier)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

        self.setStyleSheet(DIALOG_STYLE)

    def save_supplier(self):
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Required", "Supplier name is required.")
            return

        con = sqlite3.connect(DB_NAME)
        con.execute("""
            INSERT INTO suppliers (name, company, phone, address, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            name,
            self.company_input.text().strip(),
            self.phone_input.text().strip(),
            self.address_input.text().strip(),
            now_text()
        ))
        con.commit()
        con.close()
        QMessageBox.information(self, "Success", "Supplier saved successfully.")
        self.accept()


class AddPurchaseDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Purchase")
        self.setFixedWidth(560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(15)

        title = QLabel("New Purchase Entry")
        title.setObjectName("dialogTitle")
        subtitle = QLabel("Purchase stock from supplier.")
        subtitle.setObjectName("dialogSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        form = QFormLayout()
        form.setSpacing(14)

        self.invoice_input = QLineEdit(generate_invoice("PUR"))
        self.supplier_combo = QComboBox()
        self.medicine_combo = QComboBox()
        self.batch_input = QLineEdit()
        self.batch_input.setPlaceholderText("e.g. PN-001")

        self.expiry_input = QDateEdit()
        self.expiry_input.setCalendarPopup(True)
        self.expiry_input.setDate(QDate.currentDate().addYears(1))
        self.expiry_input.setDisplayFormat("dd-MM-yyyy")

        self.quantity_input = QSpinBox()
        self.quantity_input.setRange(1, 9999999)

        self.purchase_price_input = QDoubleSpinBox()
        self.purchase_price_input.setRange(0, 99999999)
        self.purchase_price_input.setDecimals(2)
        self.purchase_price_input.setPrefix("Rs. ")

        self.sale_price_input = QDoubleSpinBox()
        self.sale_price_input.setRange(0, 99999999)
        self.sale_price_input.setDecimals(2)
        self.sale_price_input.setPrefix("Rs. ")

        self.total_label = QLabel("Rs. 0.00")
        self.total_label.setObjectName("bigTotal")

        form.addRow("Purchase Invoice", self.invoice_input)
        form.addRow("Supplier *", self.supplier_combo)
        form.addRow("Medicine *", self.medicine_combo)
        form.addRow("Batch Number *", self.batch_input)
        form.addRow("Expiry Date", self.expiry_input)
        form.addRow("Quantity", self.quantity_input)
        form.addRow("Purchase Price", self.purchase_price_input)
        form.addRow("Sale Price", self.sale_price_input)
        form.addRow("Total", self.total_label)
        layout.addLayout(form)

        self.quantity_input.valueChanged.connect(self.calculate_total)
        self.purchase_price_input.valueChanged.connect(self.calculate_total)
        self.medicine_combo.currentIndexChanged.connect(self.load_medicine_prices)

        buttons = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.setObjectName("secondaryButton")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save Purchase")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.save_purchase)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

        self.setStyleSheet(DIALOG_STYLE)
        self.load_suppliers()
        self.load_medicines()
        self.calculate_total()

    def load_suppliers(self):
        self.supplier_combo.clear()
        self.supplier_combo.addItem("Select Supplier", None)
        con = sqlite3.connect(DB_NAME)
        rows = con.execute("SELECT id, name FROM suppliers ORDER BY name").fetchall()
        con.close()
        for row in rows:
            self.supplier_combo.addItem(row[1], row[0])

    def load_medicines(self):
        self.medicine_combo.clear()
        self.medicine_combo.addItem("Select Medicine", None)
        con = sqlite3.connect(DB_NAME)
        rows = con.execute("SELECT id, name FROM medicines ORDER BY name").fetchall()
        con.close()
        for row in rows:
            self.medicine_combo.addItem(row[1], row[0])

    def load_medicine_prices(self):
        medicine_id = self.medicine_combo.currentData()
        if medicine_id is None:
            return
        con = sqlite3.connect(DB_NAME)
        row = con.execute("""
            SELECT purchase_price, sale_price
            FROM medicines WHERE id = ?
        """, (medicine_id,)).fetchone()
        con.close()
        if row:
            self.purchase_price_input.setValue(row[0] or 0)
            self.sale_price_input.setValue(row[1] or 0)

    def calculate_total(self):
        total = self.quantity_input.value() * self.purchase_price_input.value()
        self.total_label.setText(f"Rs. {total:,.2f}")

    def save_purchase(self):
        supplier_id = self.supplier_combo.currentData()
        medicine_id = self.medicine_combo.currentData()
        batch = self.batch_input.text().strip()
        invoice = self.invoice_input.text().strip() or generate_invoice("PUR")

        if supplier_id is None:
            QMessageBox.warning(self, "Supplier Required", "Please select supplier.")
            return
        if medicine_id is None:
            QMessageBox.warning(self, "Medicine Required", "Please select medicine.")
            return
        if not batch:
            QMessageBox.warning(self, "Batch Required", "Batch number is required.")
            return

        quantity = self.quantity_input.value()
        purchase_price = self.purchase_price_input.value()
        sale_price = self.sale_price_input.value()
        expiry = self.expiry_input.date().toString("yyyy-MM-dd")
        total = quantity * purchase_price

        con = sqlite3.connect(DB_NAME)
        try:
            existing = con.execute("""
                SELECT id FROM medicine_batches
                WHERE medicine_id = ? AND batch_number = ?
            """, (medicine_id, batch)).fetchone()

            if existing:
                con.execute("""
                    UPDATE medicine_batches
                    SET quantity_received = quantity_received + ?,
                        quantity_available = quantity_available + ?,
                        purchase_price = ?, sale_price = ?,
                        expiry_date = ?, supplier_id = ?
                    WHERE id = ?
                """, (
                    quantity, quantity, purchase_price, sale_price,
                    expiry, supplier_id, existing[0]
                ))
            else:
                con.execute("""
                    INSERT INTO medicine_batches (
                        medicine_id, supplier_id, batch_number, expiry_date,
                        purchase_price, sale_price, quantity_received,
                        quantity_available, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    medicine_id, supplier_id, batch, expiry, purchase_price,
                    sale_price, quantity, quantity, now_text()
                ))

            con.execute("""
                INSERT INTO purchases (
                    invoice_number, supplier_id, medicine_id, batch_number,
                    expiry_date, quantity, purchase_price, sale_price,
                    total, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                invoice, supplier_id, medicine_id, batch, expiry, quantity,
                purchase_price, sale_price, total, now_text()
            ))

            con.execute("""
                UPDATE medicines
                SET stock = stock + ?, purchase_price = ?,
                    sale_price = ?, expiry_date = ?
                WHERE id = ?
            """, (
                quantity, purchase_price, sale_price, expiry, medicine_id
            ))

            con.commit()
        except Exception as error:
            con.rollback()
            con.close()
            QMessageBox.critical(self, "Purchase Error", str(error))
            return

        con.close()
        QMessageBox.information(
            self, "Purchase Saved",
            f"Purchase saved successfully.\n\nQuantity Added: {quantity}\nTotal: Rs. {total:,.2f}"
        )
        self.accept()


class ReceiptDialog(QDialog):
    def __init__(
        self,
        invoice,
        cart,
        total,
        received,
        change,
        payment_method,
        parent=None
    ):
        super().__init__(parent)

        self.invoice = invoice

        self.setWindowTitle("Sale Receipt")
        self.resize(520, 720)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel(get_setting("pharmacy_name", "PHARMACY POS"))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setObjectName("dialogTitle")
        layout.addWidget(title)

        self.receipt_view = QTextEdit()
        self.receipt_view.setReadOnly(True)

        html, _ = build_receipt_html(invoice)

        if html:
            self.receipt_view.setHtml(html)
        else:
            self.receipt_view.setPlainText("Receipt not found.")

        layout.addWidget(self.receipt_view)

        buttons = QHBoxLayout()

        print_button = QPushButton("Print Receipt")
        print_button.setObjectName("primaryButton")
        print_button.clicked.connect(self.print_receipt)

        close_button = QPushButton("Close")
        close_button.setObjectName("secondaryButton")
        close_button.clicked.connect(self.accept)

        buttons.addWidget(print_button)
        buttons.addStretch()
        buttons.addWidget(close_button)

        layout.addLayout(buttons)
        self.setStyleSheet(DIALOG_STYLE)

    def print_receipt(self):
        print_receipt_invoice(self, self.invoice)


class SalesReturnDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sales Return")
        self.setFixedWidth(560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(15)

        title = QLabel("Sales Return")
        title.setObjectName("dialogTitle")
        subtitle = QLabel("Enter the original sale invoice number.")
        subtitle.setObjectName("dialogSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        form = QFormLayout()
        form.setSpacing(14)

        self.invoice_input = QLineEdit()
        self.invoice_input.setPlaceholderText("e.g. SAL-20260817-...")
        self.medicine_combo = QComboBox()
        self.quantity_input = QSpinBox()
        self.quantity_input.setRange(1, 999999)
        self.refund_label = QLabel("Rs. 0.00")
        self.refund_label.setObjectName("bigTotal")
        self.reason_input = QLineEdit()
        self.reason_input.setPlaceholderText("e.g. Customer return")

        form.addRow("Original Invoice *", self.invoice_input)
        form.addRow("Medicine *", self.medicine_combo)
        form.addRow("Return Quantity", self.quantity_input)
        form.addRow("Refund", self.refund_label)
        form.addRow("Reason", self.reason_input)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        load_button = QPushButton("Load Invoice")
        load_button.setObjectName("secondaryButton")
        load_button.clicked.connect(self.load_invoice)

        save_button = QPushButton("Process Return")
        save_button.setObjectName("primaryButton")
        save_button.clicked.connect(self.process_return)

        buttons.addWidget(load_button)
        buttons.addStretch()
        buttons.addWidget(save_button)
        layout.addLayout(buttons)

        self.quantity_input.valueChanged.connect(self.calculate_refund)
        self.medicine_combo.currentIndexChanged.connect(self.medicine_changed)

        self.setStyleSheet(DIALOG_STYLE)

    def load_invoice(self):
        invoice = self.invoice_input.text().strip()
        if not invoice:
            QMessageBox.warning(self, "Required", "Enter invoice number.")
            return

        con = sqlite3.connect(DB_NAME)
        con.row_factory = sqlite3.Row
        rows = con.execute("""
            SELECT medicine, SUM(quantity) AS qty, SUM(total) AS total
            FROM sales
            WHERE invoice = ?
            GROUP BY medicine
            ORDER BY medicine
        """, (invoice,)).fetchall()
        con.close()

        self.medicine_combo.clear()

        if not rows:
            QMessageBox.warning(self, "Not Found", "No sale found for this invoice.")
            return

        for row in rows:
            unit_price = (row["total"] / row["qty"]) if row["qty"] else 0
            self.medicine_combo.addItem(
                f"{row['medicine']} (Sold {row['qty']})",
                {
                    "name": row["medicine"],
                    "sold_qty": int(row["qty"]),
                    "unit_price": float(unit_price)
                }
            )

        self.medicine_changed()

    def medicine_changed(self):
        data = self.medicine_combo.currentData()
        if not data:
            return

        invoice = self.invoice_input.text().strip()
        con = sqlite3.connect(DB_NAME)

        returned = con.execute("""
            SELECT COALESCE(SUM(quantity), 0)
            FROM sales_returns
            WHERE invoice = ? AND medicine = ?
        """, (invoice, data["name"])).fetchone()[0]

        con.close()

        remaining = max(0, data["sold_qty"] - int(returned or 0))
        self.quantity_input.setMaximum(max(1, remaining))
        self.quantity_input.setValue(1 if remaining > 0 else 1)

        if remaining <= 0:
            self.refund_label.setText("Fully Returned")
        else:
            self.calculate_refund()

    def calculate_refund(self):
        data = self.medicine_combo.currentData()
        if not data:
            self.refund_label.setText("Rs. 0.00")
            return
        refund = self.quantity_input.value() * data["unit_price"]
        self.refund_label.setText(f"Rs. {refund:,.2f}")

    def process_return(self):
        invoice = self.invoice_input.text().strip()
        data = self.medicine_combo.currentData()

        if not invoice or not data:
            QMessageBox.warning(self, "Required", "Load an invoice and select medicine.")
            return

        con = sqlite3.connect(DB_NAME)
        con.row_factory = sqlite3.Row

        already_returned = con.execute("""
            SELECT COALESCE(SUM(quantity), 0)
            FROM sales_returns
            WHERE invoice = ? AND medicine = ?
        """, (invoice, data["name"])).fetchone()[0]

        remaining_returnable = data["sold_qty"] - int(already_returned or 0)
        qty = self.quantity_input.value()

        if remaining_returnable <= 0:
            con.close()
            QMessageBox.warning(self, "Not Allowed", "This item is already fully returned.")
            return

        if qty > remaining_returnable:
            con.close()
            QMessageBox.warning(
                self, "Quantity Error",
                f"Only {remaining_returnable} item(s) can still be returned."
            )
            return

        medicine = con.execute("""
            SELECT id FROM medicines WHERE name = ? LIMIT 1
        """, (data["name"],)).fetchone()

        if not medicine:
            con.close()
            QMessageBox.warning(self, "Medicine Missing", "Medicine record was not found.")
            return

        medicine_id = medicine["id"]
        refund = qty * data["unit_price"]
        return_number = generate_invoice("RET")

        try:
            # Restore against recorded sale batch allocations if available
            allocations = con.execute("""
                SELECT id, batch_id, quantity
                FROM sale_batch_allocations
                WHERE invoice = ? AND medicine_id = ?
                ORDER BY id DESC
            """, (invoice, medicine_id)).fetchall()

            remaining = qty

            if allocations:
                for alloc in allocations:
                    if remaining <= 0:
                        break

                    already_restored = con.execute("""
                        SELECT COALESCE(SUM(sr.quantity), 0)
                        FROM sales_returns sr
                        WHERE sr.invoice = ? AND sr.medicine_id = ?
                    """, (invoice, medicine_id)).fetchone()[0]

                    # Simple safe restore: put returned qty into first allocation batch
                    restore = remaining
                    con.execute("""
                        UPDATE medicine_batches
                        SET quantity_available = quantity_available + ?
                        WHERE id = ?
                    """, (restore, alloc["batch_id"]))
                    remaining -= restore
                    break
            else:
                # Legacy sale: restore to earliest batch, or create a RETURN batch
                batch = con.execute("""
                    SELECT id
                    FROM medicine_batches
                    WHERE medicine_id = ?
                    ORDER BY date(expiry_date) ASC, id ASC
                    LIMIT 1
                """, (medicine_id,)).fetchone()

                if batch:
                    con.execute("""
                        UPDATE medicine_batches
                        SET quantity_available = quantity_available + ?
                        WHERE id = ?
                    """, (qty, batch["id"]))
                else:
                    med = con.execute("""
                        SELECT purchase_price, sale_price, expiry_date
                        FROM medicines WHERE id = ?
                    """, (medicine_id,)).fetchone()

                    con.execute("""
                        INSERT INTO medicine_batches (
                            medicine_id, supplier_id, batch_number, expiry_date,
                            purchase_price, sale_price, quantity_received,
                            quantity_available, created_at
                        )
                        VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        medicine_id, "RETURN-" + return_number, med[2],
                        med[0] or 0, med[1] or 0, qty, qty, now_text()
                    ))

            con.execute("""
                UPDATE medicines
                SET stock = stock + ?
                WHERE id = ?
            """, (qty, medicine_id))

            con.execute("""
                INSERT INTO sales_returns (
                    return_number, invoice, medicine_id, medicine,
                    quantity, refund_amount, reason, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                return_number, invoice, medicine_id, data["name"], qty,
                refund, self.reason_input.text().strip(), now_text()
            ))

            con.commit()
        except Exception as error:
            con.rollback()
            con.close()
            QMessageBox.critical(self, "Return Failed", str(error))
            return

        con.close()
        QMessageBox.information(
            self,
            "Return Completed",
            f"Return completed successfully.\n\nReturn No: {return_number}\nRefund: Rs. {refund:,.2f}"
        )
        self.accept()


class AddCustomerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Customer")
        self.setFixedWidth(500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(16)

        title = QLabel("Add Customer")
        title.setObjectName("dialogTitle")
        subtitle = QLabel("Save customer details for quick lookup and purchase history.")
        subtitle.setObjectName("dialogSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        form = QFormLayout()
        form.setSpacing(14)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Customer name")
        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("Phone number")
        self.address_input = QLineEdit()
        self.address_input.setPlaceholderText("Address")

        form.addRow("Customer Name *", self.name_input)
        form.addRow("Phone", self.phone_input)
        form.addRow("Address", self.address_input)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.setObjectName("secondaryButton")
        cancel.clicked.connect(self.reject)

        save = QPushButton("Save Customer")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.save_customer)

        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

        self.setStyleSheet(DIALOG_STYLE)

    def save_customer(self):
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Required", "Customer name is required.")
            return

        con = sqlite3.connect(DB_NAME)
        con.execute("""
            INSERT INTO customers (name, phone, address, created_at)
            VALUES (?, ?, ?, ?)
        """, (
            name,
            self.phone_input.text().strip(),
            self.address_input.text().strip(),
            now_text()
        ))
        con.commit()
        con.close()

        QMessageBox.information(self, "Success", "Customer saved successfully.")
        self.accept()


class AddExpenseDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Expense")
        self.setFixedWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(16)

        title = QLabel("Add Expense")
        title.setObjectName("dialogTitle")
        subtitle = QLabel("Record a pharmacy operating expense.")
        subtitle.setObjectName("dialogSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        form = QFormLayout()
        form.setSpacing(14)

        self.category_combo = QComboBox()
        self.category_combo.addItems([
            "Rent",
            "Electricity",
            "Salary",
            "Delivery",
            "Utilities",
            "Maintenance",
            "Miscellaneous"
        ])

        self.description_input = QLineEdit()
        self.description_input.setPlaceholderText("Expense details")

        self.amount_input = QDoubleSpinBox()
        self.amount_input.setRange(0.01, 999999999)
        self.amount_input.setDecimals(2)
        self.amount_input.setPrefix("Rs. ")

        self.date_input = QDateEdit()
        self.date_input.setCalendarPopup(True)
        self.date_input.setDate(QDate.currentDate())
        self.date_input.setDisplayFormat("dd-MM-yyyy")

        form.addRow("Category *", self.category_combo)
        form.addRow("Description", self.description_input)
        form.addRow("Amount *", self.amount_input)
        form.addRow("Expense Date", self.date_input)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.setObjectName("secondaryButton")
        cancel.clicked.connect(self.reject)

        save = QPushButton("Save Expense")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.save_expense)

        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

        self.setStyleSheet(DIALOG_STYLE)

    def save_expense(self):
        amount = self.amount_input.value()
        if amount <= 0:
            QMessageBox.warning(self, "Required", "Expense amount must be greater than zero.")
            return

        con = sqlite3.connect(DB_NAME)
        con.execute("""
            INSERT INTO expenses (
                category, description, amount, expense_date, created_at
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            self.category_combo.currentText(),
            self.description_input.text().strip(),
            amount,
            self.date_input.date().toString("yyyy-MM-dd"),
            now_text()
        ))
        con.commit()
        con.close()

        QMessageBox.information(self, "Success", "Expense saved successfully.")
        self.accept()


class RegistrationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        if os.path.exists(APP_ICON_FILE):
            self.setWindowIcon(QIcon(APP_ICON_FILE))

        self.setWindowTitle("Pharmacy POS Registration")
        self.setFixedWidth(610)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 25, 28, 25)
        layout.setSpacing(15)

        title = QLabel("Software Registration")
        title.setObjectName("dialogTitle")

        subtitle = QLabel(
            "Send the Machine ID to Aliyan Ali. "
            "Enter the license key you receive to activate this computer."
        )
        subtitle.setObjectName("dialogSubtitle")
        subtitle.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(subtitle)

        form = QFormLayout()
        form.setSpacing(13)

        self.machine_id = QLineEdit()
        self.machine_id.setReadOnly(True)
        self.machine_id.setText(get_machine_id())

        self.pharmacy_name = QLineEdit()
        self.owner_name = QLineEdit()
        self.phone = QLineEdit()
        self.city = QLineEdit()

        self.license_key = QTextEdit()
        self.license_key.setPlaceholderText("Paste license key here...")
        self.license_key.setFixedHeight(105)

        form.addRow("Machine ID", self.machine_id)
        form.addRow("Pharmacy Name", self.pharmacy_name)
        form.addRow("Owner Name", self.owner_name)
        form.addRow("Phone", self.phone)
        form.addRow("City", self.city)
        form.addRow("License Key *", self.license_key)

        layout.addLayout(form)

        support = QLabel("Registration / Support: Aliyan Ali | 03166965457")
        support.setObjectName("infoBox")
        support.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(support)

        buttons = QHBoxLayout()

        copy_machine = QPushButton("Copy Machine ID")
        copy_machine.setObjectName("secondaryButton")
        copy_machine.clicked.connect(self.copy_machine_id)

        activate = QPushButton("ACTIVATE SOFTWARE")
        activate.setObjectName("completeSaleButton")
        activate.clicked.connect(self.activate_license)

        buttons.addWidget(copy_machine)
        buttons.addStretch()
        buttons.addWidget(activate)

        layout.addLayout(buttons)
        self.setStyleSheet(DIALOG_STYLE)

    def copy_machine_id(self):
        QApplication.clipboard().setText(self.machine_id.text())
        QMessageBox.information(self, "Copied", "Machine ID copied.")

    def activate_license(self):
        license_key = self.license_key.toPlainText().strip()
        valid, message, payload = verify_license_key(license_key)

        if not valid:
            QMessageBox.warning(self, "Activation Failed", message)
            return

        save_activated_license(license_key, payload)

        self.pharmacy_name.setText(payload.get("pharmacy_name", ""))
        self.owner_name.setText(payload.get("owner_name", ""))
        self.phone.setText(payload.get("phone", ""))
        self.city.setText(payload.get("city", ""))

        QMessageBox.information(
            self,
            "Activation Successful",
            "Software registered successfully.\n\n"
            f"Pharmacy: {payload.get('pharmacy_name', '')}\n"
            f"Expiry: {payload.get('expires_on', '')}"
        )

        self.accept()


class LauncherDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        if os.path.exists(APP_ICON_FILE):
            self.setWindowIcon(QIcon(APP_ICON_FILE))

        self.user = None
        self.setWindowTitle("Pharmacy POS")
        self.setFixedSize(670, 500)

        root = QHBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 28)
        root.setSpacing(28)

        brand = QFrame()
        brand.setObjectName("launcherBrand")
        brand_layout = QVBoxLayout(brand)
        brand_layout.setContentsMargins(22, 22, 22, 22)

        logo = QLabel()
        logo.setObjectName("launcherLogo")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setFixedSize(180, 180)

        if os.path.exists(LOGO_FILE):
            pixmap = QPixmap(LOGO_FILE)

            if not pixmap.isNull():
                logo.setPixmap(
                    pixmap.scaled(
                        170,
                        170,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                )
            else:
                logo.setText("✚")
        else:
            logo.setText("✚")

        app_name = QLabel("PHARMACY\\nPOS")
        app_name.setObjectName("launcherAppName")
        app_name.setAlignment(Qt.AlignmentFlag.AlignCenter)

        tagline = QLabel("Pharmacy Management\n& Billing System")
        tagline.setObjectName("launcherTagline")
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)

        brand_layout.addStretch()
        brand_layout.addWidget(logo)
        brand_layout.addWidget(app_name)
        brand_layout.addWidget(tagline)
        brand_layout.addStretch()

        root.addWidget(brand, 4)

        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setSpacing(10)

        heading = QLabel("Welcome")
        heading.setObjectName("dialogTitle")

        self.license_status = QLabel("")
        self.license_status.setObjectName("licenseStatus")

        self.machine_label = QLabel("Machine ID: " + get_machine_id())
        self.machine_label.setObjectName("launcherSmall")

        panel_layout.addWidget(heading)
        panel_layout.addWidget(self.license_status)
        panel_layout.addWidget(self.machine_label)
        panel_layout.addSpacing(12)

        self.login_button = QPushButton("LOGIN")
        self.login_button.setObjectName("launcherPrimary")
        self.login_button.clicked.connect(self.open_login)

        registration_button = QPushButton("REGISTRATION")
        registration_button.setObjectName("launcherButton")
        registration_button.clicked.connect(self.open_registration)

        backup_button = QPushButton("BACKUP")
        backup_button.setObjectName("launcherButton")
        backup_button.clicked.connect(self.create_backup)

        update_button = QPushButton("UPDATE")
        update_button.setObjectName("launcherButton")
        update_button.clicked.connect(self.show_update)

        database_button = QPushButton("DATABASE")
        database_button.setObjectName("launcherButton")
        database_button.clicked.connect(self.open_database_folder)

        support_button = QPushButton("SUPPORT")
        support_button.setObjectName("launcherButton")
        support_button.clicked.connect(self.show_support)

        panel_layout.addWidget(self.login_button)
        panel_layout.addWidget(registration_button)
        panel_layout.addWidget(backup_button)
        panel_layout.addWidget(update_button)
        panel_layout.addWidget(database_button)
        panel_layout.addWidget(support_button)
        panel_layout.addStretch()

        footer = QLabel(
            "POS Software by Aliyan Ali | 03166965457\nVersion 4.1"
        )
        footer.setObjectName("launcherFooter")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        panel_layout.addWidget(footer)

        root.addWidget(panel, 6)

        self.refresh_license_status()

        self.setStyleSheet(DIALOG_STYLE + """
            #launcherBrand {
                background: #0f172a;
                border-radius: 18px;
            }
            #launcherLogo {
                color: #22c55e;
                font-size: 62px;
                font-weight: 900;
                background: transparent;
            }
            #launcherAppName {
                color: white;
                font-size: 29px;
                font-weight: 900;
            }
            #launcherTagline {
                color: #94a3b8;
                font-size: 13px;
                margin-top: 8px;
            }
            #launcherPrimary {
                background: #0f766e;
                color: white;
                border: none;
                min-height: 44px;
                border-radius: 8px;
                font-size: 15px;
                font-weight: 900;
            }
            #launcherButton {
                background: #f1f5f9;
                color: #0f172a;
                border: 1px solid #cbd5e1;
                min-height: 40px;
                border-radius: 8px;
                font-size: 14px;
                font-weight: 800;
            }
            #launcherButton:hover {
                background: #e2e8f0;
            }
            #licenseStatus {
                font-size: 14px;
                font-weight: 800;
                padding: 8px;
                border-radius: 8px;
                background: #f8fafc;
            }
            #launcherSmall {
                color: #64748b;
                font-size: 11px;
            }
            #launcherFooter {
                color: #64748b;
                font-size: 11px;
            }
        """)

    def refresh_license_status(self):
        valid, message, payload = get_license_status()

        if valid:
            expiry = payload.get("expires_on", "")
            pharmacy = payload.get("pharmacy_name", "")

            self.license_status.setText(
                f"License: ACTIVE\n{pharmacy}\nExpiry: {expiry}"
            )

            self.license_status.setStyleSheet(
                "color:#047857; background:#ecfdf5;"
                "border:1px solid #a7f3d0;"
            )

            self.login_button.setEnabled(True)

        else:
            self.license_status.setText(
                "License: NOT ACTIVE\n" + message
            )

            self.license_status.setStyleSheet(
                "color:#b91c1c; background:#fef2f2;"
                "border:1px solid #fecaca;"
            )

            self.login_button.setEnabled(False)

    def open_registration(self):
        dialog = RegistrationDialog(self)
        if dialog.exec():
            self.refresh_license_status()

    def open_login(self):
        valid, message, _ = get_license_status()

        if not valid:
            QMessageBox.warning(
                self,
                "Registration Required",
                "Software must be registered before login.\n\n" + message
            )
            return

        if is_first_run_setup_required():
            setup = FirstRunSetupDialog(self)
            if setup.exec() != QDialog.DialogCode.Accepted:
                return

        login = LoginDialog(self)
        if login.exec() == QDialog.DialogCode.Accepted:
            self.user = login.user
            self.accept()

    def create_backup(self):
        if not os.path.exists(DB_NAME):
            QMessageBox.warning(self, "Database", "Database does not exist yet.")
            return

        suggested = os.path.join(
            BACKUP_DIR,
            "pharmacy_backup_"
            + datetime.now().strftime("%Y%m%d_%H%M%S")
            + ".db"
        )

        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save Database Backup",
            suggested,
            "Database Files (*.db)"
        )

        if not filename:
            return

        if not filename.lower().endswith(".db"):
            filename += ".db"

        try:
            shutil.copy2(DB_NAME, filename)
            QMessageBox.information(
                self,
                "Backup Complete",
                "Backup created successfully."
            )
        except Exception as error:
            QMessageBox.critical(self, "Backup Failed", str(error))

    def show_update(self):
        QMessageBox.information(
            self,
            "Update",
            "Online update service will be connected in the next phase."
        )

    def open_database_folder(self):
        try:
            os.startfile(DATABASE_DIR)
        except Exception as error:
            QMessageBox.critical(self, "Database", str(error))

    def show_support(self):
        QMessageBox.information(
            self,
            "Support",
            "Pharmacy POS Support\n\nAliyan Ali\n03166965457"
        )




class FirstRunSetupDialog(QDialog):
    """
    Runs only once for a fresh pharmacy installation.
    No coding is needed for another pharmacy: enter its details here.
    """
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Pharmacy POS - First Setup")
        self.setFixedWidth(560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 28, 30, 28)
        layout.setSpacing(16)

        title = QLabel("Welcome to Pharmacy POS")
        title.setObjectName("dialogTitle")

        subtitle = QLabel(
            "This setup runs only for a new pharmacy. "
            "Enter the pharmacy details; the same EXE can then be used without changing code."
        )
        subtitle.setObjectName("dialogSubtitle")
        subtitle.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(subtitle)

        form = QFormLayout()
        form.setSpacing(14)

        self.pharmacy_name = QLineEdit()
        self.pharmacy_name.setPlaceholderText("e.g. Islamabad Pharmacy")

        self.address = QLineEdit()
        self.address.setPlaceholderText("Pharmacy address")

        self.phone = QLineEdit()
        self.phone.setPlaceholderText("Phone number")

        self.receipt_footer = QLineEdit()
        self.receipt_footer.setText("Thank you for your purchase.")

        self.admin_name = QLineEdit()
        self.admin_name.setPlaceholderText("Owner / Administrator name")

        self.admin_username = QLineEdit()
        self.admin_username.setText("admin")

        self.admin_password = QLineEdit()
        self.admin_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.admin_password.setPlaceholderText("Minimum 6 characters")

        self.confirm_password = QLineEdit()
        self.confirm_password.setEchoMode(QLineEdit.EchoMode.Password)

        form.addRow("Pharmacy Name *", self.pharmacy_name)
        form.addRow("Address", self.address)
        form.addRow("Phone", self.phone)
        form.addRow("Receipt Footer", self.receipt_footer)
        form.addRow("Admin Name", self.admin_name)
        form.addRow("Admin Username *", self.admin_username)
        form.addRow("Admin Password *", self.admin_password)
        form.addRow("Confirm Password *", self.confirm_password)

        layout.addLayout(form)

        note = QLabel(
            "Software footer is fixed as: Aliyan Ali | 03166965457"
        )
        note.setObjectName("infoBox")
        note.setWordWrap(True)
        layout.addWidget(note)

        save = QPushButton("SAVE & START PHARMACY POS")
        save.setObjectName("completeSaleButton")
        save.clicked.connect(self.save_setup)
        layout.addWidget(save)

        self.setStyleSheet(DIALOG_STYLE)

    def save_setup(self):
        name = self.pharmacy_name.text().strip()
        username = self.admin_username.text().strip()
        password = self.admin_password.text()

        if not name:
            QMessageBox.warning(self, "Required", "Pharmacy name is required.")
            return

        if not username:
            QMessageBox.warning(self, "Required", "Admin username is required.")
            return

        if len(password) < 6:
            QMessageBox.warning(
                self,
                "Password",
                "Admin password must contain at least 6 characters."
            )
            return

        if password != self.confirm_password.text():
            QMessageBox.warning(self, "Password", "Passwords do not match.")
            return

        set_setting("pharmacy_name", name)
        set_setting("address", self.address.text().strip())
        set_setting("phone", self.phone.text().strip())
        set_setting("receipt_footer", self.receipt_footer.text().strip())
        set_setting("setup_completed", "1")

        salt, password_hash = hash_password(password)

        con = sqlite3.connect(DB_NAME)

        # Replace the automatically-created first admin only on fresh setup.
        existing_admin = con.execute("""
            SELECT id
            FROM users
            WHERE username = 'admin'
            ORDER BY id
            LIMIT 1
        """).fetchone()

        if existing_admin:
            con.execute("""
                UPDATE users
                SET username = ?,
                    full_name = ?,
                    role = 'Admin',
                    password_salt = ?,
                    password_hash = ?,
                    active = 1
                WHERE id = ?
            """, (
                username,
                self.admin_name.text().strip() or "Administrator",
                salt,
                password_hash,
                existing_admin[0]
            ))
        else:
            con.execute("""
                INSERT INTO users (
                    username, full_name, role,
                    password_salt, password_hash,
                    active, created_at
                )
                VALUES (?, ?, 'Admin', ?, ?, 1, ?)
            """, (
                username,
                self.admin_name.text().strip() or "Administrator",
                salt,
                password_hash,
                now_text()
            ))

        con.commit()
        con.close()

        QMessageBox.information(
            self,
            "Setup Complete",
            "Pharmacy setup completed successfully."
        )
        self.accept()



class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.user = None

        self.setWindowTitle("Pharmacy POS Login")
        self.setFixedSize(430, 360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(35, 30, 35, 30)
        layout.setSpacing(18)

        title = QLabel(get_setting("pharmacy_name", "PHARMACY POS"))
        title.setObjectName("loginTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        subtitle = QLabel("Sign in to continue")
        subtitle.setObjectName("dialogSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(8)

        form = QFormLayout()
        form.setSpacing(14)

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Username")
        self.username_input.setText("admin")

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Password")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)

        form.addRow("Username", self.username_input)
        form.addRow("Password", self.password_input)
        layout.addLayout(form)

        note = QLabel(
            "First login: admin / admin123\n"
            "Change this password from Users after login."
        )
        note.setObjectName("loginNote")
        note.setWordWrap(True)
        layout.addWidget(note)

        login_button = QPushButton("LOGIN")
        login_button.setObjectName("completeSaleButton")
        login_button.clicked.connect(self.try_login)
        layout.addWidget(login_button)

        self.password_input.returnPressed.connect(self.try_login)

        self.setStyleSheet(DIALOG_STYLE + """
            #loginTitle {
                font-size: 27px;
                font-weight: 900;
                color: #111827;
            }
            #loginNote {
                color: #92400e;
                background: #fffbeb;
                border: 1px solid #fde68a;
                border-radius: 8px;
                padding: 10px;
            }
        """)

    def try_login(self):
        username = self.username_input.text().strip()
        password = self.password_input.text()

        if not username or not password:
            QMessageBox.warning(self, "Required", "Enter username and password.")
            return

        con = sqlite3.connect(DB_NAME)
        con.row_factory = sqlite3.Row

        row = con.execute("""
            SELECT *
            FROM users
            WHERE lower(username) = lower(?)
              AND active = 1
        """, (username,)).fetchone()

        con.close()

        if not row or not verify_password(
            password,
            row["password_salt"],
            row["password_hash"]
        ):
            QMessageBox.warning(self, "Login Failed", "Invalid username or password.")
            return

        self.user = {
            "id": row["id"],
            "username": row["username"],
            "full_name": row["full_name"] or row["username"],
            "role": row["role"]
        }

        self.accept()


class AddUserDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Add User")
        self.setFixedWidth(500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(16)

        title = QLabel("Add User")
        title.setObjectName("dialogTitle")
        subtitle = QLabel("Create an Admin or Cashier login.")
        subtitle.setObjectName("dialogSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        form = QFormLayout()
        form.setSpacing(14)

        self.full_name_input = QLineEdit()
        self.username_input = QLineEdit()

        self.role_combo = QComboBox()
        self.role_combo.addItems(["Cashier", "Admin"])

        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)

        self.confirm_input = QLineEdit()
        self.confirm_input.setEchoMode(QLineEdit.EchoMode.Password)

        form.addRow("Full Name", self.full_name_input)
        form.addRow("Username *", self.username_input)
        form.addRow("Role *", self.role_combo)
        form.addRow("Password *", self.password_input)
        form.addRow("Confirm Password *", self.confirm_input)

        layout.addLayout(form)

        buttons = QHBoxLayout()

        cancel = QPushButton("Cancel")
        cancel.setObjectName("secondaryButton")
        cancel.clicked.connect(self.reject)

        save = QPushButton("Create User")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.save_user)

        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

        self.setStyleSheet(DIALOG_STYLE)

    def save_user(self):
        username = self.username_input.text().strip()
        password = self.password_input.text()

        if not username:
            QMessageBox.warning(self, "Required", "Username is required.")
            return

        if len(password) < 6:
            QMessageBox.warning(
                self,
                "Password",
                "Password must contain at least 6 characters."
            )
            return

        if password != self.confirm_input.text():
            QMessageBox.warning(self, "Password", "Passwords do not match.")
            return

        salt, password_hash = hash_password(password)

        con = sqlite3.connect(DB_NAME)

        try:
            con.execute("""
                INSERT INTO users (
                    username, full_name, role,
                    password_salt, password_hash,
                    active, created_at
                )
                VALUES (?, ?, ?, ?, ?, 1, ?)
            """, (
                username,
                self.full_name_input.text().strip(),
                self.role_combo.currentText(),
                salt,
                password_hash,
                now_text()
            ))

            con.commit()

        except sqlite3.IntegrityError:
            con.close()
            QMessageBox.warning(
                self,
                "Duplicate Username",
                "This username already exists."
            )
            return

        con.close()

        QMessageBox.information(self, "Success", "User created successfully.")
        self.accept()


class ChangePasswordDialog(QDialog):
    def __init__(self, user_id, parent=None):
        super().__init__(parent)

        self.user_id = user_id
        self.setWindowTitle("Change Password")
        self.setFixedWidth(450)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(16)

        title = QLabel("Change Password")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)

        form = QFormLayout()

        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)

        self.confirm_input = QLineEdit()
        self.confirm_input.setEchoMode(QLineEdit.EchoMode.Password)

        form.addRow("New Password", self.password_input)
        form.addRow("Confirm Password", self.confirm_input)
        layout.addLayout(form)

        save = QPushButton("Update Password")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.save_password)
        layout.addWidget(save)

        self.setStyleSheet(DIALOG_STYLE)

    def save_password(self):
        password = self.password_input.text()

        if len(password) < 6:
            QMessageBox.warning(
                self,
                "Password",
                "Password must contain at least 6 characters."
            )
            return

        if password != self.confirm_input.text():
            QMessageBox.warning(self, "Password", "Passwords do not match.")
            return

        salt, password_hash = hash_password(password)

        con = sqlite3.connect(DB_NAME)
        con.execute("""
            UPDATE users
            SET password_salt = ?, password_hash = ?
            WHERE id = ?
        """, (salt, password_hash, self.user_id))
        con.commit()
        con.close()

        QMessageBox.information(self, "Success", "Password updated successfully.")
        self.accept()


class PharmacyPOS(QMainWindow):
    def __init__(self, current_user):
        super().__init__()

        if os.path.exists(APP_ICON_FILE):
            self.setWindowIcon(QIcon(APP_ICON_FILE))

        global CURRENT_RECEIPT_USER

        self.current_user = current_user
        CURRENT_RECEIPT_USER = current_user.get("full_name") or current_user.get("username") or "Admin"

        valid_license, license_message, _ = get_license_status()

        if not valid_license:
            QMessageBox.critical(
                None,
                "License Required",
                "Pharmacy POS cannot start without a valid registration.\n\n"
                + license_message
            )
            raise RuntimeError("Valid license required")

        self.cart = []
        self.setWindowTitle(get_setting("pharmacy_name", "PHARMACY POS"))
        self.resize(1400, 850)
        self.build_ui()
        self.apply_style()
        self.show_dashboard()

    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)

        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("pharmaSidebar")
        sidebar.setFixedWidth(215)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 0, 0, 12)
        side.setSpacing(0)

        brand = QFrame()
        brand.setObjectName("pharmaBrand")
        brand_l = QVBoxLayout(brand)
        brand_l.setContentsMargins(16, 16, 16, 14)

        logo = QLabel("✣  PharmaCare")
        logo.setObjectName("pharmaBrandTitle")
        brand_l.addWidget(logo)

        user = QLabel(self.current_user.get("full_name") or self.current_user.get("username") or "ADMIN USER")
        user.setObjectName("pharmaUserName")
        user.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_l.addWidget(user)

        online = QLabel("● Online")
        online.setObjectName("pharmaOnline")
        online.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_l.addWidget(online)
        side.addWidget(brand)

        items = [
            ("⌂", "Dashboard", self.show_dashboard),
            ("▤", "Invoice", self.show_pos),
            ("👤", "Customer", self.show_customers),
            ("💊", "Medicine", self.show_medicines),
            ("🏭", "Manufacturer", self.show_suppliers),
            ("🛒", "Purchase", self.show_purchase),
            ("▥", "Stock", self.show_stock),
            ("↩", "Return", self.show_returns),
            ("▦", "Report", self.show_reports),
            ("₨", "Accounts", self.show_expenses),
            ("⚠", "Expiry Alerts", self.show_expiry),
            ("🧾", "Sales History", self.show_sales_history),
        ]

        if self.current_user["role"] == "Admin":
            items += [
                ("👥", "Users", self.show_users),
                ("⚙", "Settings", self.show_settings),
            ]

        for icon, label, action in items:
            b = QPushButton(f"{icon}   {label}")
            b.setObjectName("pharmaNavButton")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(action)
            side.addWidget(b)

        side.addStretch()

        logout_side = QPushButton("Logout")
        logout_side.setObjectName("pharmaSideLogout")
        logout_side.clicked.connect(self.logout)
        side.addWidget(logout_side)

        version = QLabel("Pharmacy POS v5.1")
        version.setObjectName("pharmaSidebarFooter")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side.addWidget(version)

        shell.addWidget(sidebar)

        main = QFrame()
        main.setObjectName("pharmaContent")
        main_l = QVBoxLayout(main)
        main_l.setContentsMargins(0, 0, 0, 0)
        main_l.setSpacing(0)

        topbar = QFrame()
        topbar.setObjectName("pharmaTopbar")
        topbar.setFixedHeight(58)
        top_l = QHBoxLayout(topbar)
        top_l.setContentsMargins(16, 7, 16, 7)

        self.page_title = QLabel("Dashboard")
        self.page_title.setObjectName("pharmaPageTitle")
        top_l.addWidget(self.page_title)
        top_l.addStretch()

        for title, fn in [
            ("Invoice", self.show_pos),
            ("Customer Receive", self.show_customers),
            ("Manufacturer Payment", self.show_suppliers),
            ("Purchase", self.show_purchase),
        ]:
            b = QPushButton(title)
            b.setObjectName("pharmaQuickButton")
            b.clicked.connect(fn)
            top_l.addWidget(b)

        top_l.addSpacing(8)
        top_l.addWidget(QLabel("🔔   ⚠   ⚙"))

        main_l.addWidget(topbar)

        self.stack = QStackedWidget()
        self.dashboard_page = self.create_dashboard_page()
        self.medicines_page = self.create_medicines_page()
        self.purchase_page = self.create_purchase_page()
        self.pos_page = self.create_pos_page()
        self.stock_page = self.create_stock_page()
        self.supplier_page = self.create_supplier_page()
        self.expiry_page = self.create_expiry_page()
        self.returns_page = self.create_returns_page()
        self.customers_page = self.create_customers_page()
        self.expenses_page = self.create_expenses_page()
        self.reports_page = self.create_reports_page()
        self.users_page = self.create_users_page()
        self.settings_page = self.create_settings_page()
        self.sales_history_page = self.create_sales_history_page()
        self.placeholder_page = self.create_placeholder_page()

        for page in [
            self.dashboard_page, self.medicines_page, self.purchase_page,
            self.pos_page, self.stock_page, self.supplier_page,
            self.expiry_page, self.returns_page, self.customers_page,
            self.expenses_page, self.reports_page, self.users_page,
            self.settings_page, self.sales_history_page, self.placeholder_page
        ]:
            self.stack.addWidget(page)

        main_l.addWidget(self.stack, 1)
        shell.addWidget(main, 1)

    def show_support_dialog(self):
        QMessageBox.information(
            self,
            "Pharmacy POS Help",
            "Pharmacy POS Support\n\nAliyan Ali\n03166965457"
        )

    def create_dashboard_page(self):
        page = QWidget()
        page.setObjectName("pharmaDashboard")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)

        breadcrumb = QLabel("Dashboard  /  Home")
        breadcrumb.setObjectName("pharmaBreadcrumb")
        layout.addWidget(breadcrumb)

        cards = QGridLayout()
        cards.setSpacing(8)

        self.sale_total_card = DashboardMetricCard(
            "Sale Total", "Rs. 0", "#35b7ae", "Click for Sales Report"
        )
        self.expense_total_card = DashboardMetricCard(
            "Expense", "Rs. 0", "#8d5bc8", "Click for Expense Report"
        )
        self.purchasing_total_card = DashboardMetricCard(
            "Purchasing", "Rs. 0", "#f0aa46", "Click for Purchase Report"
        )
        self.current_stock_card = DashboardMetricCard(
            "Current Stock", "Rs. 0", "#7b9a50", "Click for Stock Report"
        )
        self.payable_card = DashboardMetricCard(
            "Payable", "Rs. 0", "#ee8e88", "Click for Payable Report"
        )
        self.receivable_card = DashboardMetricCard(
            "Receivable", "Rs. 0", "#68b8c5", "Click for Receivable Report"
        )

        metric_cards = [
            self.sale_total_card, self.expense_total_card, self.purchasing_total_card,
            self.current_stock_card, self.payable_card, self.receivable_card
        ]
        for i, card in enumerate(metric_cards):
            cards.addWidget(card, 0, i)
            cards.setColumnStretch(i, 1)

        self.sale_total_card.clicked.connect(lambda: self.open_dashboard_report("Sales"))
        self.expense_total_card.clicked.connect(lambda: self.open_dashboard_report("Expenses"))
        self.purchasing_total_card.clicked.connect(lambda: self.open_dashboard_report("Purchases"))
        self.current_stock_card.clicked.connect(lambda: self.open_dashboard_report("Stock"))
        self.payable_card.clicked.connect(lambda: self.open_dashboard_report("Payable"))
        self.receivable_card.clicked.connect(lambda: self.open_dashboard_report("Receivable"))

        layout.addLayout(cards)

        middle = QHBoxLayout()
        middle.setSpacing(10)

        graph_card = QFrame()
        graph_card.setObjectName("pharmaWhiteCard")
        graph_l = QVBoxLayout(graph_card)
        graph_title = QLabel("Monthly Progress Report")
        graph_title.setObjectName("pharmaCardHeading")
        graph_l.addWidget(graph_title)
        self.sales_chart = SalesChartWidget()
        self.sales_chart.setMinimumHeight(300)
        graph_l.addWidget(self.sales_chart, 1)
        middle.addWidget(graph_card, 7)

        today_card = QFrame()
        today_card.setObjectName("pharmaWhiteCard")
        today_l = QVBoxLayout(today_card)
        today_title = QLabel("Today's Report")
        today_title.setObjectName("pharmaCardHeading")
        today_l.addWidget(today_title)
        self.today_report_label = QLabel("")
        self.today_report_label.setObjectName("pharmaTodayReport")
        self.today_report_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        today_l.addWidget(self.today_report_label, 1)
        middle.addWidget(today_card, 3)

        layout.addLayout(middle, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(10)

        recent_card = QFrame()
        recent_card.setObjectName("pharmaWhiteCard")
        recent_l = QVBoxLayout(recent_card)
        recent_title = QLabel("Recent Sales")
        recent_title.setObjectName("pharmaCardHeading")
        recent_l.addWidget(recent_title)
        self.sales_table = QTableWidget()
        self.sales_table.setColumnCount(5)
        self.sales_table.setHorizontalHeaderLabels([
            "Invoice", "Medicine", "Quantity", "Total", "Date / Time"
        ])
        setup_table(self.sales_table)
        self.sales_table.setMaximumHeight(155)
        recent_l.addWidget(self.sales_table)
        bottom.addWidget(recent_card, 2)

        summary_card = QFrame()
        summary_card.setObjectName("pharmaWhiteCard")
        summary_l = QVBoxLayout(summary_card)
        summary_title = QLabel("Profit / Expense Snapshot")
        summary_title.setObjectName("pharmaCardHeading")
        summary_l.addWidget(summary_title)
        self.dashboard_profit_label = QLabel(
            "Gross Profit: Rs. 0\nExpenses: Rs. 0\nProfit / Loss: Rs. 0"
        )
        self.dashboard_profit_label.setObjectName("pharmaTodayReport")
        summary_l.addWidget(self.dashboard_profit_label)
        pnl_btn = QPushButton("Open Profit & Loss Report")
        pnl_btn.setObjectName("pharmaQuickButton")
        pnl_btn.clicked.connect(lambda: self.open_dashboard_report("Profit & Loss"))
        summary_l.addWidget(pnl_btn)
        bottom.addWidget(summary_card, 1)

        layout.addLayout(bottom)

        return page

    def create_medicines_page(self):
        """Reference-style Inventory Control screen for pharmacy stock."""
        page = QWidget()
        page.setObjectName("inventoryControlPage")

        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(8)

        # Header
        header = QFrame()
        header.setObjectName("inventoryHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 8, 10, 8)

        title = QLabel("▣  INVENTORY CONTROL")
        title.setObjectName("inventoryTitle")
        header_layout.addWidget(title)
        header_layout.addStretch()

        default_tax = QPushButton("Update Default Tax")
        default_tax.setObjectName("inventoryHeaderButton")
        default_tax.clicked.connect(self.update_default_inventory_tax)
        header_layout.addWidget(default_tax)

        import_stock = QPushButton("Import Stock")
        import_stock.setObjectName("inventoryHeaderButton")
        import_stock.clicked.connect(self.import_inventory_stock)
        header_layout.addWidget(import_stock)

        layout.addWidget(header)

        # Main entry panel
        entry = QFrame()
        entry.setObjectName("inventoryEntryPanel")
        entry_layout = QVBoxLayout(entry)
        entry_layout.setContentsMargins(10, 10, 10, 10)
        entry_layout.setSpacing(8)

        labels = QGridLayout()
        labels.setHorizontalSpacing(6)
        labels.setVerticalSpacing(3)

        self.inv_item_code = QLineEdit()
        self.inv_item_code.setPlaceholderText("Barcode / Item Code")

        self.inv_item_name = QLineEdit()
        self.inv_item_name.setPlaceholderText("Medicine name")

        self.inv_category = QComboBox()
        self.inv_category.setEditable(True)
        self.inv_category.addItem("")

        self.inv_cost = QDoubleSpinBox()
        self.inv_cost.setRange(0, 99999999)
        self.inv_cost.setDecimals(2)

        self.inv_retail = QDoubleSpinBox()
        self.inv_retail.setRange(0, 99999999)
        self.inv_retail.setDecimals(2)

        self.inv_wholesale = QDoubleSpinBox()
        self.inv_wholesale.setRange(0, 99999999)
        self.inv_wholesale.setDecimals(2)

        self.inv_tax = QDoubleSpinBox()
        self.inv_tax.setRange(0, 100)
        self.inv_tax.setDecimals(2)
        try:
            self.inv_tax.setValue(float(get_setting("default_tax_rate", "0") or 0))
        except Exception:
            pass

        self.inv_opening_qty = QSpinBox()
        self.inv_opening_qty.setRange(0, 9999999)

        self.inv_scheme = QLineEdit()
        self.inv_scheme.setPlaceholderText("Scheme")

        self.inv_reorder = QSpinBox()
        self.inv_reorder.setRange(0, 9999999)

        self.inv_location = QLineEdit()
        self.inv_location.setPlaceholderText("Rack / Shelf")

        self.inv_batch = QLineEdit()
        self.inv_batch.setPlaceholderText("Batch No.")

        self.inv_expiry = QDateEdit()
        self.inv_expiry.setCalendarPopup(True)
        self.inv_expiry.setDate(QDate.currentDate().addYears(1))
        self.inv_expiry.setDisplayFormat("dd-MM-yyyy")

        fields = [
            ("ITEM CODE", self.inv_item_code),
            ("ITEM NAME", self.inv_item_name),
            ("CATEGORY", self.inv_category),
            ("COST", self.inv_cost),
            ("RETAIL", self.inv_retail),
            ("WHOLE SALE", self.inv_wholesale),
            ("TAX RATE %", self.inv_tax),
            ("OPENING QTY", self.inv_opening_qty),
            ("SCHEME", self.inv_scheme),
            ("REORDER", self.inv_reorder),
            ("LOCATION", self.inv_location),
            ("BATCH NO.", self.inv_batch),
            ("EXPIRY", self.inv_expiry),
        ]

        # 7 fields first row, 6 fields second row for readable full-screen layout.
        for index, (label_text, widget) in enumerate(fields):
            row_group = 0 if index < 7 else 1
            col = index if index < 7 else index - 7
            base_row = row_group * 2

            lbl = QLabel(label_text)
            lbl.setObjectName("inventoryFieldLabel")
            labels.addWidget(lbl, base_row, col)
            if label_text == "CATEGORY":
                category_wrap = QWidget()
                category_row = QHBoxLayout(category_wrap)
                category_row.setContentsMargins(0, 0, 0, 0)
                category_row.setSpacing(3)
                category_row.addWidget(widget, 1)
                category_add = QPushButton("+")
                category_add.setObjectName("categoryAddButton")
                category_add.setToolTip("Add / manage medicine categories")
                category_add.setFixedWidth(34)
                category_add.clicked.connect(self.open_category_manager)
                category_row.addWidget(category_add)
                labels.addWidget(category_wrap, base_row + 1, col)
            else:
                labels.addWidget(widget, base_row + 1, col)

            if index < 7:
                labels.setColumnStretch(col, 1)

        entry_layout.addLayout(labels)

        info = QHBoxLayout()
        info.setSpacing(8)

        self.inv_in_hand = QLabel("In Hand   0")
        self.inv_today_purchase = QLabel("Today's Purchasing   0")
        self.inv_reorder_status = QLabel("Re Order   0")
        self.inv_invoice_amount = QLabel("Invoice Bill Amount   Rs. 0.00")

        for widget in [
            self.inv_in_hand,
            self.inv_today_purchase,
            self.inv_reorder_status,
            self.inv_invoice_amount,
        ]:
            widget.setObjectName("inventoryInfoBox")
            info.addWidget(widget)

        info.addStretch()
        entry_layout.addLayout(info)
        layout.addWidget(entry)

        # Grid
        self.medicine_table = QTableWidget()
        self.medicine_table.setColumnCount(12)
        self.medicine_table.setHorizontalHeaderLabels([
            "ITEM CODE", "DESCRIPTION", "CATEGORY", "QTY", "COST",
            "WHOLE SALE", "RETAIL Rs.", "BATCH", "EXPIRY",
            "LOCATION", "TAX %", "REORDER"
        ])
        setup_table(self.medicine_table)
        self.medicine_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.medicine_table.itemSelectionChanged.connect(
            self.inventory_selection_changed
        )
        layout.addWidget(self.medicine_table, 1)

        # Bottom search/action strip
        bottom = QFrame()
        bottom.setObjectName("inventoryBottomBar")
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(10, 7, 10, 7)

        search_label = QLabel("Search by Barcode / Item Name")
        search_label.setObjectName("inventorySearchLabel")
        bottom_layout.addWidget(search_label)

        self.inventory_search = QLineEdit()
        self.inventory_search.setPlaceholderText("Scan barcode or type item name...")
        self.inventory_search.returnPressed.connect(self.load_medicines)
        bottom_layout.addWidget(self.inventory_search, 1)

        find_button = QPushButton("Find")
        find_button.setObjectName("inventoryActionButton")
        find_button.clicked.connect(self.load_medicines)
        bottom_layout.addWidget(find_button)

        clear_button = QPushButton("New / Clear")
        clear_button.setObjectName("inventoryActionButton")
        clear_button.clicked.connect(self.clear_inventory_form)
        bottom_layout.addWidget(clear_button)

        self.inventory_save_button = QPushButton("Save")
        self.inventory_save_button.setObjectName("inventorySaveButton")
        self.inventory_save_button.clicked.connect(self.save_inventory_item)
        bottom_layout.addWidget(self.inventory_save_button)

        self.inventory_update_button = QPushButton("Update")
        self.inventory_update_button.setObjectName("inventoryActionButton")
        self.inventory_update_button.clicked.connect(self.update_inventory_item)
        bottom_layout.addWidget(self.inventory_update_button)

        delete_button = QPushButton("Delete")
        delete_button.setObjectName("dangerButton")
        delete_button.clicked.connect(self.delete_inventory_item)
        bottom_layout.addWidget(delete_button)

        layout.addWidget(bottom)

        # Keyboard workflow
        connect_enter_to_next([
            self.inv_item_code,
            self.inv_item_name,
            self.inv_cost,
            self.inv_retail,
            self.inv_wholesale,
            self.inv_tax,
            self.inv_opening_qty,
            self.inv_scheme,
            self.inv_reorder,
            self.inv_location,
            self.inv_batch,
            self.inv_expiry,
        ])

        self.inventory_selected_id = None
        return page

    def create_purchase_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 25, 30, 30)
        layout.setSpacing(20)

        top = QHBoxLayout()
        title = QLabel("Purchase Management")
        title.setObjectName("sectionHeading")
        add_button = QPushButton("+ New Purchase")
        add_button.setObjectName("primaryButton")
        add_button.clicked.connect(self.open_purchase)
        top.addWidget(title)
        top.addStretch()
        top.addWidget(add_button)
        layout.addLayout(top)

        self.purchase_table = QTableWidget()
        self.purchase_table.setColumnCount(9)
        self.purchase_table.setHorizontalHeaderLabels([
            "Invoice", "Supplier", "Medicine", "Batch", "Expiry",
            "Qty", "Buy Price", "Total", "Date"
        ])
        setup_table(self.purchase_table)
        layout.addWidget(self.purchase_table)
        return page

    def create_stock_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 25, 30, 30)
        layout.setSpacing(20)

        title = QLabel("Batch Stock")
        title.setObjectName("sectionHeading")
        layout.addWidget(title)

        self.stock_table = QTableWidget()
        self.stock_table.setColumnCount(8)
        self.stock_table.setHorizontalHeaderLabels([
            "Medicine", "Batch", "Supplier", "Expiry", "Buy Price",
            "Sale Price", "Received", "Available"
        ])
        setup_table(self.stock_table)
        layout.addWidget(self.stock_table)
        return page

    def create_supplier_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 25, 30, 30)
        layout.setSpacing(20)

        top = QHBoxLayout()
        title = QLabel("Suppliers")
        title.setObjectName("sectionHeading")
        add_button = QPushButton("+ Add Supplier")
        add_button.setObjectName("primaryButton")
        add_button.clicked.connect(self.open_add_supplier)
        top.addWidget(title)
        top.addStretch()
        top.addWidget(add_button)
        layout.addLayout(top)

        self.supplier_table = QTableWidget()
        self.supplier_table.setColumnCount(5)
        self.supplier_table.setHorizontalHeaderLabels([
            "ID", "Supplier", "Company", "Phone", "Address"
        ])
        setup_table(self.supplier_table)
        layout.addWidget(self.supplier_table)
        return page

    def create_expiry_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 25, 30, 30)
        layout.setSpacing(20)

        top = QHBoxLayout()
        title = QLabel("Expiry Alerts")
        title.setObjectName("sectionHeading")

        self.expiry_filter = QComboBox()
        self.expiry_filter.addItems([
            "Expired",
            "Next 30 Days",
            "Next 60 Days",
            "Next 90 Days",
            "All Active Batches"
        ])
        self.expiry_filter.currentIndexChanged.connect(self.load_expiry_alerts)

        top.addWidget(title)
        top.addStretch()
        top.addWidget(self.expiry_filter)
        layout.addLayout(top)

        self.expiry_table = QTableWidget()
        self.expiry_table.setColumnCount(7)
        self.expiry_table.setHorizontalHeaderLabels([
            "Medicine", "Batch", "Supplier", "Expiry",
            "Available", "Sale Price", "Status"
        ])
        setup_table(self.expiry_table)
        layout.addWidget(self.expiry_table)
        return page

    def create_returns_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 25, 30, 30)
        layout.setSpacing(20)

        top = QHBoxLayout()
        title = QLabel("Sales Returns")
        title.setObjectName("sectionHeading")

        new_return = QPushButton("+ New Sales Return")
        new_return.setObjectName("primaryButton")
        new_return.clicked.connect(self.open_sales_return)

        top.addWidget(title)
        top.addStretch()
        top.addWidget(new_return)
        layout.addLayout(top)

        self.return_table = QTableWidget()
        self.return_table.setColumnCount(7)
        self.return_table.setHorizontalHeaderLabels([
            "Return No", "Original Invoice", "Medicine", "Qty",
            "Refund", "Reason", "Date"
        ])
        setup_table(self.return_table)
        layout.addWidget(self.return_table)
        return page

    def create_customers_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 25, 30, 30)
        layout.setSpacing(20)

        top = QHBoxLayout()
        title = QLabel("Customers")
        title.setObjectName("sectionHeading")

        add_button = QPushButton("+ Add Customer")
        add_button.setObjectName("primaryButton")
        add_button.clicked.connect(self.open_add_customer)

        top.addWidget(title)
        top.addStretch()
        top.addWidget(add_button)
        layout.addLayout(top)

        self.customer_table = QTableWidget()
        self.customer_table.setColumnCount(5)
        self.customer_table.setHorizontalHeaderLabels([
            "ID", "Customer", "Phone", "Address", "Added"
        ])
        setup_table(self.customer_table)
        layout.addWidget(self.customer_table)
        return page

    def create_expenses_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 25, 30, 30)
        layout.setSpacing(20)

        top = QHBoxLayout()
        title = QLabel("Expenses")
        title.setObjectName("sectionHeading")

        self.expense_total_label = QLabel("Total: Rs. 0.00")
        self.expense_total_label.setObjectName("reportValue")

        add_button = QPushButton("+ Add Expense")
        add_button.setObjectName("primaryButton")
        add_button.clicked.connect(self.open_add_expense)

        top.addWidget(title)
        top.addStretch()
        top.addWidget(self.expense_total_label)
        top.addSpacing(15)
        top.addWidget(add_button)
        layout.addLayout(top)

        self.expense_table = QTableWidget()
        self.expense_table.setColumnCount(6)
        self.expense_table.setHorizontalHeaderLabels([
            "ID", "Category", "Description", "Amount", "Expense Date", "Created"
        ])
        setup_table(self.expense_table)
        layout.addWidget(self.expense_table)
        return page

    def create_reports_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 22)
        layout.setSpacing(12)

        top = QHBoxLayout()
        title = QLabel("Admin / Business Reports")
        title.setObjectName("sectionHeading")
        top.addWidget(title)

        self.report_type = QComboBox()
        self.report_type.addItems([
            "Sales", "Expenses", "Purchases", "Stock",
            "Payable", "Receivable", "Profit & Loss"
        ])
        self.report_type.currentTextChanged.connect(self.load_reports)
        top.addWidget(self.report_type)

        top.addStretch()
        layout.addLayout(top)

        presets = QHBoxLayout()
        for label, code in [
            ("Today", "today"),
            ("Yesterday", "yesterday"),
            ("This Week", "week"),
            ("This Month", "month"),
            ("Last Month", "last_month"),
            ("This Year", "year"),
        ]:
            b = QPushButton(label)
            b.setObjectName("pharmaQuickButton")
            b.clicked.connect(lambda checked=False, c=code: self.set_report_period(c))
            presets.addWidget(b)

        presets.addStretch()

        self.report_from = QDateEdit()
        self.report_from.setCalendarPopup(True)
        self.report_from.setDisplayFormat("dd-MM-yyyy")

        self.report_to = QDateEdit()
        self.report_to.setCalendarPopup(True)
        self.report_to.setDisplayFormat("dd-MM-yyyy")

        today = QDate.currentDate()
        self.report_from.setDate(QDate(today.year(), today.month(), 1))
        self.report_to.setDate(today)

        refresh = QPushButton("Custom Range / Refresh")
        refresh.setObjectName("primaryButton")
        refresh.clicked.connect(self.load_reports)

        presets.addWidget(QLabel("From"))
        presets.addWidget(self.report_from)
        presets.addWidget(QLabel("To"))
        presets.addWidget(self.report_to)
        presets.addWidget(refresh)
        layout.addLayout(presets)

        cards = QGridLayout()
        cards.setSpacing(8)

        self.report_gross_sales = StatCard("Gross Sales", "Rs. 0", "Before returns")
        self.report_returns = StatCard("Returns", "Rs. 0", "Refunded value")
        self.report_net_sales = StatCard("Net Sales", "Rs. 0", "After returns")
        self.report_cogs = StatCard("Cost of Goods", "Rs. 0", "Batch purchase cost")
        self.report_expenses = StatCard("Expenses", "Rs. 0", "Operating expenses")
        self.report_profit_loss = StatCard("Profit / Loss", "Rs. 0", "Net sales - cost - expenses")

        cards.addWidget(self.report_gross_sales, 0, 0)
        cards.addWidget(self.report_returns, 0, 1)
        cards.addWidget(self.report_net_sales, 0, 2)
        cards.addWidget(self.report_cogs, 1, 0)
        cards.addWidget(self.report_expenses, 1, 1)
        cards.addWidget(self.report_profit_loss, 1, 2)
        layout.addLayout(cards)

        self.report_context_label = QLabel("Sales Report")
        self.report_context_label.setObjectName("sectionHeading")
        layout.addWidget(self.report_context_label)

        self.report_table = QTableWidget()
        setup_table(self.report_table)
        layout.addWidget(self.report_table, 1)

        return page

    def create_pos_page(self):
        page = QWidget()
        main = QVBoxLayout(page)
        main.setContentsMargins(25, 20, 25, 25)
        main.setSpacing(15)

        search_card = QFrame()
        search_card.setObjectName("whiteCard")
        search_layout = QHBoxLayout(search_card)

        self.pos_search = QLineEdit()
        self.pos_search.setPlaceholderText(
            "Search medicine, generic name or scan barcode..."
        )
        self.pos_search.setObjectName("posSearchInput")

        search_button = QPushButton("Search")
        search_button.setObjectName("primaryButton")
        search_button.clicked.connect(self.search_pos_medicines)
        self.pos_search.returnPressed.connect(self.search_pos_medicines)

        search_layout.addWidget(self.pos_search, 1)
        search_layout.addWidget(search_button)
        main.addWidget(search_card)

        keyboard_hint = QLabel(
            "Barcode scanner: scan + Enter • Name search: type + Enter • "
            "Use ↑/↓ to select • Enter adds selected item"
        )
        keyboard_hint.setObjectName("infoBox")
        main.addWidget(keyboard_hint)

        invoice_bar = QFrame()
        invoice_bar.setObjectName("invoiceBar")
        invoice_bar_layout = QHBoxLayout(invoice_bar)
        invoice_bar_layout.setContentsMargins(10, 6, 10, 6)
        invoice_bar_layout.addWidget(QLabel("Customer"))
        self.pos_customer = QComboBox()
        self.pos_customer.setMinimumWidth(210)
        invoice_bar_layout.addWidget(self.pos_customer)
        add_customer = QPushButton("+")
        add_customer.setObjectName("categoryAddButton")
        add_customer.setFixedWidth(36)
        add_customer.clicked.connect(self.open_add_customer_from_pos)
        invoice_bar_layout.addWidget(add_customer)
        invoice_bar_layout.addStretch()
        invoice_bar_layout.addWidget(QLabel("Invoice Discount"))
        self.pos_discount = QDoubleSpinBox()
        self.pos_discount.setRange(0, 999999999)
        self.pos_discount.setDecimals(2)
        self.pos_discount.setPrefix("Rs. ")
        self.pos_discount.valueChanged.connect(self.refresh_cart)
        invoice_bar_layout.addWidget(self.pos_discount)
        main.addWidget(invoice_bar)

        body = QHBoxLayout()
        body.setSpacing(15)

        left = QFrame()
        left.setObjectName("whiteCard")
        left_layout = QVBoxLayout(left)

        products_title = QLabel("Medicine Search Results")
        products_title.setObjectName("sectionHeading")
        left_layout.addWidget(products_title)

        self.pos_result_table = QTableWidget()
        self.pos_result_table.setColumnCount(6)
        self.pos_result_table.setHorizontalHeaderLabels([
            "ID", "Medicine", "Generic", "Barcode", "Price", "Stock"
        ])
        setup_table(self.pos_result_table)
        self.pos_result_table.doubleClicked.connect(self.add_selected_to_cart)
        self.pos_result_table.itemActivated.connect(self.add_selected_to_cart)
        left_layout.addWidget(self.pos_result_table)

        add_cart_button = QPushButton("Add Selected to Cart")
        add_cart_button.setObjectName("primaryButton")
        add_cart_button.clicked.connect(self.add_selected_to_cart)
        left_layout.addWidget(add_cart_button)

        right = QFrame()
        right.setObjectName("whiteCard")
        right_layout = QVBoxLayout(right)

        cart_title = QLabel("Current Sale")
        cart_title.setObjectName("sectionHeading")
        right_layout.addWidget(cart_title)

        self.cart_table = QTableWidget()
        self.cart_table.setColumnCount(4)
        self.cart_table.setHorizontalHeaderLabels([
            "Medicine", "Price", "Qty", "Total"
        ])
        setup_table(self.cart_table)
        right_layout.addWidget(self.cart_table)

        cart_buttons = QHBoxLayout()

        minus_button = QPushButton("- Qty")
        minus_button.setObjectName("secondaryButton")
        minus_button.clicked.connect(self.decrease_cart_qty)

        plus_button = QPushButton("+ Qty")
        plus_button.setObjectName("secondaryButton")
        plus_button.clicked.connect(self.increase_cart_qty)

        remove_button = QPushButton("Remove")
        remove_button.setObjectName("dangerButton")
        remove_button.clicked.connect(self.remove_cart_item)

        cart_buttons.addWidget(minus_button)
        cart_buttons.addWidget(plus_button)
        cart_buttons.addWidget(remove_button)
        right_layout.addLayout(cart_buttons)

        total_box = QFrame()
        total_box.setObjectName("totalBox")
        total_layout = QVBoxLayout(total_box)

        self.pos_subtotal_label = QLabel("Subtotal: Rs. 0.00")
        self.pos_subtotal_label.setObjectName("cardTitle")
        total_layout.addWidget(self.pos_subtotal_label)
        total_title = QLabel("Payable Total")
        total_title.setObjectName("cardTitle")
        self.pos_total_label = QLabel("Rs. 0.00")
        self.pos_total_label.setObjectName("posGrandTotal")
        total_layout.addWidget(total_title)
        total_layout.addWidget(self.pos_total_label)
        right_layout.addWidget(total_box)

        payment_form = QFormLayout()
        self.payment_method = QComboBox()
        self.payment_method.setObjectName("posPaymentMethod")
        self.payment_method.addItems(["Cash", "Card", "Bank Transfer"])
        self.payment_method.currentIndexChanged.connect(self.payment_method_changed)

        self.cash_received = QDoubleSpinBox()
        self.cash_received.setObjectName("posCashReceived")
        self.cash_received.setRange(0, 999999999)
        self.cash_received.setDecimals(2)
        self.cash_received.setPrefix("Rs. ")
        self.cash_received.valueChanged.connect(self.update_change)
        try:
            self.cash_received.lineEdit().setObjectName("posCashReceivedLine")
            self.cash_received.lineEdit().returnPressed.connect(self.complete_sale)
        except Exception:
            pass

        self.change_label = QLabel("Rs. 0.00")
        self.change_label.setObjectName("changeLabel")

        payment_form.addRow("Payment Method", self.payment_method)
        payment_form.addRow("Amount Received", self.cash_received)
        payment_form.addRow("Change", self.change_label)
        right_layout.addLayout(payment_form)

        complete_button = QPushButton("COMPLETE SALE")
        complete_button.setObjectName("completeSaleButton")
        complete_button.clicked.connect(self.complete_sale)
        right_layout.addWidget(complete_button)

        body.addWidget(left, 6)
        body.addWidget(right, 5)
        main.addLayout(body)
        return page

    def create_sales_history_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 22, 30, 30)
        layout.setSpacing(16)

        top = QHBoxLayout()

        title = QLabel("Sales History")
        title.setObjectName("sectionHeading")

        self.sales_history_search = QLineEdit()
        self.sales_history_search.setPlaceholderText(
            "Invoice number, medicine name or payment method..."
        )
        self.sales_history_search.returnPressed.connect(self.load_sales_history)

        self.sales_history_from = QDateEdit()
        self.sales_history_from.setCalendarPopup(True)
        self.sales_history_from.setDate(QDate.currentDate().addMonths(-1))
        self.sales_history_from.setDisplayFormat("dd-MM-yyyy")

        self.sales_history_to = QDateEdit()
        self.sales_history_to.setCalendarPopup(True)
        self.sales_history_to.setDate(QDate.currentDate())
        self.sales_history_to.setDisplayFormat("dd-MM-yyyy")

        search_button = QPushButton("Search")
        search_button.setObjectName("primaryButton")
        search_button.clicked.connect(self.load_sales_history)

        top.addWidget(title)
        top.addStretch()
        top.addWidget(self.sales_history_search, 1)
        top.addWidget(self.sales_history_from)
        top.addWidget(self.sales_history_to)
        top.addWidget(search_button)

        layout.addLayout(top)

        hint = QLabel(
            "Keyboard: type invoice / medicine and press Enter. "
            "Select a row and press Enter to open receipt."
        )
        hint.setObjectName("infoBox")
        layout.addWidget(hint)

        self.sales_history_table = QTableWidget()
        self.sales_history_table.setColumnCount(8)
        self.sales_history_table.setHorizontalHeaderLabels([
            "Invoice", "Items", "Qty", "Gross", "Returned",
            "Net", "Payment", "Date / Time"
        ])
        setup_table(self.sales_history_table)
        self.sales_history_table.doubleClicked.connect(self.open_selected_old_receipt)
        self.sales_history_table.itemActivated.connect(self.open_selected_old_receipt)
        layout.addWidget(self.sales_history_table)

        buttons = QHBoxLayout()

        open_button = QPushButton("Open / Reprint Selected Invoice")
        open_button.setObjectName("primaryButton")
        open_button.clicked.connect(self.open_selected_old_receipt)

        print_button = QPushButton("Direct Print Selected")
        print_button.setObjectName("secondaryButton")
        print_button.clicked.connect(self.print_selected_old_receipt)

        buttons.addStretch()
        buttons.addWidget(open_button)
        buttons.addWidget(print_button)
        layout.addLayout(buttons)

        return page

    def create_users_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 25, 30, 30)
        layout.setSpacing(20)

        top = QHBoxLayout()

        title = QLabel("Users & Roles")
        title.setObjectName("sectionHeading")

        add_button = QPushButton("+ Add User")
        add_button.setObjectName("primaryButton")
        add_button.clicked.connect(self.open_add_user)

        password_button = QPushButton("Change My Password")
        password_button.setObjectName("secondaryButton")
        password_button.clicked.connect(self.change_my_password)

        top.addWidget(title)
        top.addStretch()
        top.addWidget(password_button)
        top.addWidget(add_button)
        layout.addLayout(top)

        info = QLabel(
            "Admin: full access.   Cashier: Dashboard, POS Billing, Stock, "
            "Customers, Expiry Alerts and Returns."
        )
        info.setObjectName("infoBox")
        info.setWordWrap(True)
        layout.addWidget(info)

        self.users_table = QTableWidget()
        self.users_table.setColumnCount(6)
        self.users_table.setHorizontalHeaderLabels([
            "ID", "Username", "Full Name", "Role", "Status", "Created"
        ])
        setup_table(self.users_table)
        layout.addWidget(self.users_table)

        action_row = QHBoxLayout()

        toggle_button = QPushButton("Activate / Deactivate Selected")
        toggle_button.setObjectName("secondaryButton")
        toggle_button.clicked.connect(self.toggle_selected_user)

        reset_button = QPushButton("Reset Selected Password")
        reset_button.setObjectName("secondaryButton")
        reset_button.clicked.connect(self.reset_selected_user_password)

        action_row.addStretch()
        action_row.addWidget(toggle_button)
        action_row.addWidget(reset_button)
        layout.addLayout(action_row)

        return page

    def create_settings_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 25, 30, 30)
        layout.setSpacing(18)

        title = QLabel("Settings")
        title.setObjectName("sectionHeading")
        layout.addWidget(title)

        details_card = QFrame()
        details_card.setObjectName("whiteCard")
        details_layout = QVBoxLayout(details_card)

        section = QLabel("Pharmacy & Receipt Details")
        section.setObjectName("sectionHeading")
        details_layout.addWidget(section)

        form = QFormLayout()
        form.setSpacing(14)

        self.settings_pharmacy_name = QLineEdit()
        self.settings_address = QLineEdit()
        self.settings_phone = QLineEdit()
        self.settings_receipt_footer = QLineEdit()

        self.settings_low_stock = QSpinBox()
        self.settings_low_stock.setRange(1, 9999)
        self.settings_receipt_width = QComboBox()
        self.settings_receipt_width.addItems(["80 mm", "58 mm"])

        form.addRow("Pharmacy Name", self.settings_pharmacy_name)
        form.addRow("Address", self.settings_address)
        form.addRow("Phone", self.settings_phone)
        form.addRow("Receipt Footer", self.settings_receipt_footer)
        form.addRow("Low Stock Alert At", self.settings_low_stock)
        form.addRow("Thermal Receipt Paper", self.settings_receipt_width)

        details_layout.addLayout(form)

        save_settings = QPushButton("Save Settings")
        save_settings.setObjectName("primaryButton")
        save_settings.clicked.connect(self.save_settings)
        details_layout.addWidget(save_settings)

        layout.addWidget(details_card)

        backup_card = QFrame()
        backup_card.setObjectName("whiteCard")
        backup_layout = QVBoxLayout(backup_card)

        backup_title = QLabel("Database Backup & Restore")
        backup_title.setObjectName("sectionHeading")
        backup_layout.addWidget(backup_title)

        backup_text = QLabel(
            "Backup creates a safe copy of pharmacy.db. "
            "Restore replaces the current database with a selected backup."
        )
        backup_text.setObjectName("infoBox")
        backup_text.setWordWrap(True)
        backup_layout.addWidget(backup_text)

        buttons = QHBoxLayout()

        backup_button = QPushButton("Create Backup")
        backup_button.setObjectName("primaryButton")
        backup_button.clicked.connect(self.create_database_backup)

        restore_button = QPushButton("Restore Backup")
        restore_button.setObjectName("dangerButton")
        restore_button.clicked.connect(self.restore_database_backup)

        open_folder_button = QPushButton("Open Data Folder")
        open_folder_button.setObjectName("secondaryButton")
        open_folder_button.clicked.connect(self.open_data_folder)

        new_pharmacy_button = QPushButton("Prepare Fresh Database")
        new_pharmacy_button.setObjectName("secondaryButton")
        new_pharmacy_button.clicked.connect(self.prepare_fresh_database_copy)

        buttons.addWidget(backup_button)
        buttons.addWidget(restore_button)
        buttons.addWidget(open_folder_button)
        buttons.addWidget(new_pharmacy_button)
        buttons.addStretch()

        backup_layout.addLayout(buttons)
        layout.addWidget(backup_card)
        layout.addStretch()

        return page

    def create_placeholder_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        label = QLabel("This module will be added next.")
        label.setObjectName("placeholder")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        return page

    def load_categories_into_inventory(self):
        if not hasattr(self, "inv_category"):
            return
        current = self.inv_category.currentText().strip()
        con = sqlite3.connect(DB_NAME)
        rows = con.execute(
            "SELECT name FROM categories WHERE active = 1 ORDER BY name COLLATE NOCASE"
        ).fetchall()
        # Include legacy categories already stored on medicines.
        legacy = con.execute(
            "SELECT DISTINCT category FROM medicines WHERE COALESCE(category, '') <> '' ORDER BY category COLLATE NOCASE"
        ).fetchall()
        con.close()
        names = []
        for row in list(rows) + list(legacy):
            name = str(row[0] or '').strip()
            if name and name not in names:
                names.append(name)
        self.inv_category.blockSignals(True)
        self.inv_category.clear()
        self.inv_category.addItem("")
        self.inv_category.addItems(names)
        if current:
            idx = self.inv_category.findText(current, Qt.MatchFlag.MatchFixedString)
            if idx >= 0:
                self.inv_category.setCurrentIndex(idx)
            else:
                self.inv_category.setEditText(current)
        self.inv_category.blockSignals(False)

    def open_category_manager(self):
        dialog = AddCategoryDialog(self)
        dialog.exec()
        self.load_categories_into_inventory()

    def open_add_medicine(self):
        dialog = AddMedicineDialog(self)
        if dialog.exec():
            self.load_medicines()
            self.load_stock()
            self.refresh_dashboard()

    def open_add_supplier(self):
        dialog = AddSupplierDialog(self)
        if dialog.exec():
            self.load_suppliers()

    def open_purchase(self):
        con = sqlite3.connect(DB_NAME)
        supplier_count = con.execute("SELECT COUNT(*) FROM suppliers").fetchone()[0]
        medicine_count = con.execute("SELECT COUNT(*) FROM medicines").fetchone()[0]
        con.close()

        if supplier_count == 0:
            QMessageBox.warning(self, "Supplier Required", "First add at least one supplier.")
            return

        if medicine_count == 0:
            QMessageBox.warning(self, "Medicine Required", "First add at least one medicine.")
            return

        dialog = AddPurchaseDialog(self)
        if dialog.exec():
            self.load_purchases()
            self.load_medicines()
            self.load_stock()
            self.refresh_dashboard()

    def open_sales_return(self):
        dialog = SalesReturnDialog(self)
        if dialog.exec():
            self.load_returns()
            self.load_medicines()
            self.load_stock()
            self.refresh_dashboard()

    def open_add_customer(self):
        dialog = AddCustomerDialog(self)
        if dialog.exec():
            self.load_customers()

    def open_add_expense(self):
        dialog = AddExpenseDialog(self)
        if dialog.exec():
            self.load_expenses()
            self.load_reports()

    def open_add_user(self):
        if self.current_user["role"] != "Admin":
            QMessageBox.warning(self, "Access Denied", "Admin access is required.")
            return

        dialog = AddUserDialog(self)
        if dialog.exec():
            self.load_users()

    def change_my_password(self):
        dialog = ChangePasswordDialog(self.current_user["id"], self)
        dialog.exec()

    def reset_selected_user_password(self):
        if self.current_user["role"] != "Admin":
            return

        row = self.users_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Select User", "Select a user first.")
            return

        user_id = int(self.users_table.item(row, 0).text())
        username = self.users_table.item(row, 1).text()

        password, ok = QInputDialog.getText(
            self,
            "Reset Password",
            f"Enter new password for {username}:",
            QLineEdit.EchoMode.Password
        )

        if not ok:
            return

        if len(password) < 6:
            QMessageBox.warning(
                self,
                "Password",
                "Password must contain at least 6 characters."
            )
            return

        salt, password_hash = hash_password(password)

        con = sqlite3.connect(DB_NAME)
        con.execute("""
            UPDATE users
            SET password_salt = ?, password_hash = ?
            WHERE id = ?
        """, (salt, password_hash, user_id))
        con.commit()
        con.close()

        QMessageBox.information(self, "Success", "Password reset successfully.")

    def toggle_selected_user(self):
        if self.current_user["role"] != "Admin":
            return

        row = self.users_table.currentRow()

        if row < 0:
            QMessageBox.warning(self, "Select User", "Select a user first.")
            return

        user_id = int(self.users_table.item(row, 0).text())
        username = self.users_table.item(row, 1).text()
        status = self.users_table.item(row, 4).text()

        if user_id == self.current_user["id"]:
            QMessageBox.warning(
                self,
                "Not Allowed",
                "You cannot deactivate your own logged-in account."
            )
            return

        new_active = 0 if status == "Active" else 1

        answer = QMessageBox.question(
            self,
            "Confirm",
            f"{'Deactivate' if new_active == 0 else 'Activate'} user {username}?"
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        con = sqlite3.connect(DB_NAME)
        con.execute(
            "UPDATE users SET active = ? WHERE id = ?",
            (new_active, user_id)
        )
        con.commit()
        con.close()

        self.load_users()

    def logout(self):
        answer = QMessageBox.question(
            self,
            "Logout",
            "Logout from Pharmacy POS?"
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        QApplication.quit()

    def show_dashboard(self):
        self.page_title.setText("Dashboard")
        self.stack.setCurrentWidget(self.dashboard_page)
        self.refresh_dashboard()

    def show_medicines(self):
        self.page_title.setText("Medicines")
        self.stack.setCurrentWidget(self.medicines_page)
        self.load_categories_into_inventory()
        self.load_medicines()

    def show_purchase(self):
        self.page_title.setText("Purchase")
        self.stack.setCurrentWidget(self.purchase_page)
        self.load_purchases()

    def show_pos(self):
        self.page_title.setText("POS Billing")
        self.stack.setCurrentWidget(self.pos_page)
        self.load_pos_customers()
        self.search_pos_medicines()
        self.pos_search.setFocus()

    def show_stock(self):
        self.page_title.setText("Stock")
        self.stack.setCurrentWidget(self.stock_page)
        self.load_stock()

    def show_suppliers(self):
        self.page_title.setText("Suppliers")
        self.stack.setCurrentWidget(self.supplier_page)
        self.load_suppliers()

    def show_expiry(self):
        self.page_title.setText("Expiry Alerts")
        self.stack.setCurrentWidget(self.expiry_page)
        self.load_expiry_alerts()

    def show_returns(self):
        self.page_title.setText("Returns")
        self.stack.setCurrentWidget(self.returns_page)
        self.load_returns()

    def show_customers(self):
        self.page_title.setText("Customers")
        self.stack.setCurrentWidget(self.customers_page)
        self.load_customers()

    def show_expenses(self):
        self.page_title.setText("Expenses")
        self.stack.setCurrentWidget(self.expenses_page)
        self.load_expenses()

    def show_reports(self):
        self.page_title.setText("Reports")
        self.stack.setCurrentWidget(self.reports_page)
        self.load_reports()

    def show_sales_history(self):
        self.page_title.setText("Sales History")
        self.stack.setCurrentWidget(self.sales_history_page)
        self.load_sales_history()
        self.sales_history_search.setFocus()

    def show_users(self):
        if self.current_user["role"] != "Admin":
            QMessageBox.warning(self, "Access Denied", "Admin access is required.")
            return

        self.page_title.setText("Users")
        self.stack.setCurrentWidget(self.users_page)
        self.load_users()

    def show_settings(self):
        if self.current_user["role"] != "Admin":
            QMessageBox.warning(self, "Access Denied", "Admin access is required.")
            return

        self.page_title.setText("Settings")
        self.stack.setCurrentWidget(self.settings_page)
        self.load_settings()

    def show_placeholder(self):
        button = self.sender()
        if button:
            self.page_title.setText(button.text())
        self.stack.setCurrentWidget(self.placeholder_page)

    def search_pos_medicines(self):
        search = self.pos_search.text().strip()

        # Keyboard-first checkout:
        # after scanning/adding items, press Enter on an empty search box
        # to move directly to Payment Method.
        if not search and self.cart:
            self.payment_method.setFocus()
            return

        con = sqlite3.connect(DB_NAME)
        con.row_factory = sqlite3.Row

        if search:
            # Exact barcode has first priority.
            exact_barcode = con.execute("""
                SELECT id, name, generic_name, barcode, sale_price, stock
                FROM medicines
                WHERE barcode = ?
                LIMIT 1
            """, (search,)).fetchone()

            if exact_barcode:
                con.close()

                self.pos_result_table.setRowCount(0)
                self.add_medicine_to_cart(exact_barcode["id"])
                self.pos_search.clear()
                self.pos_search.setFocus()
                return

            value = f"%{search}%"

            rows = con.execute("""
                SELECT id, name, generic_name, barcode, sale_price, stock
                FROM medicines
                WHERE name LIKE ?
                   OR generic_name LIKE ?
                   OR barcode LIKE ?
                ORDER BY
                    CASE
                        WHEN lower(name) = lower(?) THEN 0
                        WHEN name LIKE ? THEN 1
                        ELSE 2
                    END,
                    name
                LIMIT 100
            """, (
                value,
                value,
                value,
                search,
                search + "%"
            )).fetchall()

        else:
            rows = con.execute("""
                SELECT id, name, generic_name, barcode, sale_price, stock
                FROM medicines
                ORDER BY name
                LIMIT 100
            """).fetchall()

        con.close()

        self.pos_result_table.setRowCount(0)

        for row in rows:
            table_row = self.pos_result_table.rowCount()
            self.pos_result_table.insertRow(table_row)

            values = [
                row["id"],
                row["name"],
                row["generic_name"],
                row["barcode"],
                f"Rs. {row['sale_price']:,.2f}",
                row["stock"]
            ]

            for column, value in enumerate(values):
                self.pos_result_table.setItem(
                    table_row,
                    column,
                    QTableWidgetItem(str(value or ""))
                )

        # If name search returns exactly one result, Enter adds it immediately.
        if search and len(rows) == 1:
            self.add_medicine_to_cart(rows[0]["id"])
            self.pos_search.clear()
            self.pos_search.setFocus()
            return

        # Multiple matches: automatically highlight first result and focus table.
        if search and rows:
            self.pos_result_table.selectRow(0)
            self.pos_result_table.setFocus()


    def add_selected_to_cart(self, *args):
        row = self.pos_result_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Select Medicine", "Please select a medicine.")
            return

        id_item = self.pos_result_table.item(row, 0)
        if not id_item:
            return

        self.add_medicine_to_cart(int(id_item.text()))
        self.pos_search.clear()
        self.pos_search.setFocus()

    def add_medicine_to_cart(self, medicine_id):
        con = sqlite3.connect(DB_NAME)
        con.row_factory = sqlite3.Row
        medicine = con.execute("""
            SELECT id, name, sale_price, stock
            FROM medicines WHERE id = ?
        """, (medicine_id,)).fetchone()
        con.close()

        if not medicine:
            return

        available_stock = int(medicine["stock"] or 0)

        if available_stock <= 0:
            QMessageBox.warning(self, "Out of Stock", f"{medicine['name']} is out of stock.")
            return

        for item in self.cart:
            if item["id"] == medicine_id:
                if item["qty"] >= available_stock:
                    QMessageBox.warning(self, "Stock Limit", "No more stock available.")
                    return
                item["qty"] += 1
                self.refresh_cart()
                for i, cart_item in enumerate(self.cart):
                    if cart_item["id"] == medicine_id:
                        self.cart_table.selectRow(i)
                        break
                return

        self.cart.append({
            "id": medicine["id"],
            "name": medicine["name"],
            "price": float(medicine["sale_price"] or 0),
            "qty": 1
        })
        self.refresh_cart()
        if self.cart_table.rowCount() > 0:
            self.cart_table.selectRow(self.cart_table.rowCount() - 1)

    def load_pos_customers(self):
        if not hasattr(self, "pos_customer"):
            return
        current_data = self.pos_customer.currentData() if self.pos_customer.count() else None
        con = sqlite3.connect(DB_NAME)
        rows = con.execute("SELECT id, name, phone FROM customers ORDER BY name COLLATE NOCASE").fetchall()
        con.close()
        self.pos_customer.clear()
        self.pos_customer.addItem("Walking Customer", None)
        for row in rows:
            label = row[1] + (f" — {row[2]}" if row[2] else "")
            self.pos_customer.addItem(label, row[0])
        if current_data is not None:
            idx = self.pos_customer.findData(current_data)
            if idx >= 0:
                self.pos_customer.setCurrentIndex(idx)

    def open_add_customer_from_pos(self):
        dialog = AddCustomerDialog(self)
        if dialog.exec():
            self.load_pos_customers()

    def sale_payable_total(self):
        subtotal = self.cart_total()
        discount = self.pos_discount.value() if hasattr(self, "pos_discount") else 0
        return max(0, subtotal - discount)

    def cart_total(self):
        return sum(item["price"] * item["qty"] for item in self.cart)

    def refresh_cart(self):
        self.cart_table.setRowCount(0)

        for item in self.cart:
            row = self.cart_table.rowCount()
            self.cart_table.insertRow(row)
            line_total = item["price"] * item["qty"]

            values = [
                item["name"], f"Rs. {item['price']:,.2f}",
                item["qty"], f"Rs. {line_total:,.2f}"
            ]

            for column, value in enumerate(values):
                self.cart_table.setItem(
                    row, column, QTableWidgetItem(str(value))
                )

        subtotal = self.cart_total()
        total = self.sale_payable_total()
        if hasattr(self, "pos_subtotal_label"):
            self.pos_subtotal_label.setText(f"Subtotal: Rs. {subtotal:,.2f}")
        self.pos_total_label.setText(f"Rs. {total:,.2f}")

        if self.payment_method.currentText() != "Cash":
            self.cash_received.setValue(total)

        self.update_change()

    def increase_cart_qty(self):
        row = self.cart_table.currentRow()
        if row < 0 and self.cart:
            row = len(self.cart) - 1
            self.cart_table.selectRow(row)
        if row < 0:
            return

        item = self.cart[row]
        con = sqlite3.connect(DB_NAME)
        stock_row = con.execute(
            "SELECT stock FROM medicines WHERE id = ?", (item["id"],)
        ).fetchone()
        con.close()

        available = int(stock_row[0] or 0) if stock_row else 0

        if item["qty"] >= available:
            QMessageBox.warning(self, "Stock Limit", "No more stock available.")
            return

        item["qty"] += 1
        self.refresh_cart()
        self.cart_table.selectRow(row)

    def decrease_cart_qty(self):
        row = self.cart_table.currentRow()
        if row < 0 and self.cart:
            row = len(self.cart) - 1
            self.cart_table.selectRow(row)
        if row < 0:
            return

        if self.cart[row]["qty"] > 1:
            self.cart[row]["qty"] -= 1
            self.refresh_cart()
            if row < self.cart_table.rowCount():
                self.cart_table.selectRow(row)
        else:
            self.cart.pop(row)
            self.refresh_cart()
            if self.cart:
                self.cart_table.selectRow(min(row, len(self.cart) - 1))

    def remove_cart_item(self):
        row = self.cart_table.currentRow()
        if row < 0 and self.cart:
            row = len(self.cart) - 1
            self.cart_table.selectRow(row)
        if row < 0:
            return
        self.cart.pop(row)
        self.refresh_cart()
        if self.cart:
            self.cart_table.selectRow(min(row, len(self.cart) - 1))

    def payment_method_changed(self):
        total = self.sale_payable_total()

        if self.payment_method.currentText() == "Cash":
            self.cash_received.setEnabled(True)
        else:
            self.cash_received.setEnabled(False)
            self.cash_received.setValue(total)

        self.update_change()

    def update_change(self):
        total = self.sale_payable_total()
        payment_method = self.payment_method.currentText()
        received = self.cash_received.value()

        change = max(0, received - total) if payment_method == "Cash" else 0
        self.change_label.setText(f"Rs. {change:,.2f}")

    def complete_sale(self):
        if not self.cart:
            QMessageBox.warning(self, "Empty Cart", "Please add medicine to cart.")
            return

        subtotal = self.cart_total()
        discount = self.pos_discount.value() if hasattr(self, "pos_discount") else 0
        total = self.sale_payable_total()
        payment_method = self.payment_method.currentText()
        received = self.cash_received.value()

        if payment_method == "Cash" and received < total:
            QMessageBox.warning(
                self, "Insufficient Cash",
                f"Total Bill: Rs. {total:,.2f}\nReceived: Rs. {received:,.2f}"
            )
            return

        if payment_method != "Cash":
            received = total

        change = max(0, received - total) if payment_method == "Cash" else 0
        invoice = generate_invoice("SAL")

        con = sqlite3.connect(DB_NAME)
        con.row_factory = sqlite3.Row

        try:
            for item in self.cart:
                stock_row = con.execute(
                    "SELECT stock FROM medicines WHERE id = ?", (item["id"],)
                ).fetchone()

                if not stock_row or int(stock_row["stock"] or 0) < item["qty"]:
                    raise Exception(f"Not enough stock for {item['name']}.")

            for item in self.cart:
                required_qty = int(item["qty"])

                batches = con.execute("""
                    SELECT id, quantity_available
                    FROM medicine_batches
                    WHERE medicine_id = ? AND quantity_available > 0
                    ORDER BY
                        CASE WHEN expiry_date IS NULL OR expiry_date = '' THEN 1 ELSE 0 END,
                        date(expiry_date) ASC,
                        id ASC
                """, (item["id"],)).fetchall()

                total_batch_stock = sum(
                    int(batch["quantity_available"] or 0) for batch in batches
                )

                if total_batch_stock < required_qty:
                    raise Exception(
                        f"Batch stock mismatch for {item['name']}.\n"
                        f"Batch stock: {total_batch_stock}\nRequired: {required_qty}"
                    )

                remaining = required_qty

                for batch in batches:
                    if remaining <= 0:
                        break

                    available = int(batch["quantity_available"] or 0)
                    deduct = min(remaining, available)

                    con.execute("""
                        UPDATE medicine_batches
                        SET quantity_available = quantity_available - ?
                        WHERE id = ?
                    """, (deduct, batch["id"]))

                    con.execute("""
                        INSERT INTO sale_batch_allocations (
                            invoice, medicine_id, batch_id, quantity, created_at
                        )
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        invoice, item["id"], batch["id"], deduct, now_text()
                    ))

                    remaining -= deduct

                con.execute("""
                    UPDATE medicines
                    SET stock = stock - ?
                    WHERE id = ?
                """, (required_qty, item["id"]))

                line_total = item["price"] * item["qty"]

                con.execute("""
                    INSERT INTO sales (
                        invoice, medicine, quantity, total, created_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    invoice, item["name"], item["qty"], line_total, now_text()
                ))

            con.execute("""
                INSERT INTO payments (
                    invoice, subtotal, received, change_amount,
                    payment_method, created_at, customer_id, discount, tax, total_due
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                invoice, subtotal, received, change, payment_method, now_text(),
                self.pos_customer.currentData() if hasattr(self, "pos_customer") else None,
                discount, 0, total
            ))

            con.commit()

        except Exception as error:
            con.rollback()
            con.close()
            QMessageBox.critical(self, "Sale Failed", str(error))
            return

        con.close()

        receipt_cart = [item.copy() for item in self.cart]
        self.cart.clear()
        self.refresh_cart()
        self.cash_received.setValue(0)
        if hasattr(self, "pos_discount"):
            self.pos_discount.setValue(0)
        if hasattr(self, "pos_customer"):
            self.pos_customer.setCurrentIndex(0)
        self.payment_method.setCurrentIndex(0)
        self.search_pos_medicines()
        self.refresh_dashboard()

        QMessageBox.information(
            self, "Sale Completed",
            f"Sale completed successfully.\n\nInvoice: {invoice}\nTotal: Rs. {total:,.2f}"
        )

        receipt = ReceiptDialog(
            invoice, receipt_cart, total, received, change, payment_method, self
        )
        receipt.exec()

        self.pos_search.setFocus()

    def refresh_dashboard(self):
        con = sqlite3.connect(DB_NAME)
        con.row_factory = sqlite3.Row
        today = datetime.now().strftime("%Y-%m-%d")

        gross_sales = float(con.execute("""
            SELECT COALESCE(SUM(total), 0)
            FROM sales WHERE date(created_at) = ?
        """, (today,)).fetchone()[0] or 0)

        returns = float(con.execute("""
            SELECT COALESCE(SUM(refund_amount), 0)
            FROM sales_returns WHERE date(created_at) = ?
        """, (today,)).fetchone()[0] or 0)

        net_sales = gross_sales - returns

        today_expenses = float(con.execute("""
            SELECT COALESCE(SUM(amount), 0)
            FROM expenses
            WHERE date(expense_date) = ?
        """, (today,)).fetchone()[0] or 0)

        today_purchases = float(con.execute("""
            SELECT COALESCE(SUM(total), 0)
            FROM purchases
            WHERE date(created_at) = ?
        """, (today,)).fetchone()[0] or 0)

        current_stock_value = float(con.execute("""
            SELECT COALESCE(SUM(stock * purchase_price), 0)
            FROM medicines
        """).fetchone()[0] or 0)

        today_cogs = float(con.execute("""
            SELECT COALESCE(SUM(a.quantity * b.purchase_price), 0)
            FROM sale_batch_allocations a
            JOIN medicine_batches b ON b.id = a.batch_id
            WHERE EXISTS (
                SELECT 1 FROM sales s
                WHERE s.invoice = a.invoice
                  AND date(s.created_at) = ?
            )
        """, (today,)).fetchone()[0] or 0)

        payable_total = 0.0
        receivable_total = 0.0

        rows = con.execute("""
            SELECT invoice, medicine, quantity, total, created_at
            FROM sales
            ORDER BY id DESC
            LIMIT 10
        """).fetchall()

        chart_labels = []
        chart_sales = []
        chart_purchases = []

        for offset in range(6, -1, -1):
            day = datetime.now() - timedelta(days=offset)
            day_key = day.strftime("%Y-%m-%d")
            chart_labels.append(day.strftime("%a"))

            day_gross = float(con.execute("""
                SELECT COALESCE(SUM(total), 0)
                FROM sales WHERE date(created_at) = ?
            """, (day_key,)).fetchone()[0] or 0)

            day_returns = float(con.execute("""
                SELECT COALESCE(SUM(refund_amount), 0)
                FROM sales_returns WHERE date(created_at) = ?
            """, (day_key,)).fetchone()[0] or 0)

            day_purchase = float(con.execute("""
                SELECT COALESCE(SUM(total), 0)
                FROM purchases WHERE date(created_at) = ?
            """, (day_key,)).fetchone()[0] or 0)

            chart_sales.append(max(0.0, day_gross - day_returns))
            chart_purchases.append(day_purchase)

        today_invoice_count = con.execute("""
            SELECT COUNT(DISTINCT invoice)
            FROM sales WHERE date(created_at) = ?
        """, (today,)).fetchone()[0]

        today_cash = float(con.execute("""
            SELECT COALESCE(SUM(received - change_amount), 0)
            FROM payments
            WHERE date(created_at) = ? AND payment_method = 'Cash'
        """, (today,)).fetchone()[0] or 0)

        today_bank = float(con.execute("""
            SELECT COALESCE(SUM(total_due), 0)
            FROM payments
            WHERE date(created_at) = ? AND payment_method != 'Cash'
        """, (today,)).fetchone()[0] or 0)

        con.close()

        self.sale_total_card.value_label.setText(f"Rs. {net_sales:,.0f}")
        self.expense_total_card.value_label.setText(f"Rs. {today_expenses:,.0f}")
        self.purchasing_total_card.value_label.setText(f"Rs. {today_purchases:,.0f}")
        self.current_stock_card.value_label.setText(f"Rs. {current_stock_value:,.0f}")
        self.payable_card.value_label.setText(f"Rs. {payable_total:,.0f}")
        self.receivable_card.value_label.setText(f"Rs. {receivable_total:,.0f}")

        self.sales_chart.set_data(chart_labels, chart_sales, chart_purchases)

        self.today_report_label.setText(
            "Today's Report\n\n"
            f"Total Invoices        {today_invoice_count}\n"
            f"Total Sales           Rs. {net_sales:,.0f}\n"
            f"Total Purchase        Rs. {today_purchases:,.0f}\n"
            f"Cash Received         Rs. {today_cash:,.0f}\n"
            f"Bank / Card           Rs. {today_bank:,.0f}\n"
            f"Expenses              Rs. {today_expenses:,.0f}"
        )

        gross_profit = net_sales - today_cogs
        pnl = gross_profit - today_expenses
        self.dashboard_profit_label.setText(
            f"Gross Profit: Rs. {gross_profit:,.0f}\n"
            f"Expenses: Rs. {today_expenses:,.0f}\n"
            f"Profit / Loss: Rs. {pnl:,.0f}"
        )

        self.sales_table.setRowCount(0)
        for row in rows:
            r = self.sales_table.rowCount()
            self.sales_table.insertRow(r)
            values = [
                row["invoice"], row["medicine"], row["quantity"],
                f"Rs. {float(row['total'] or 0):,.2f}", row["created_at"]
            ]
            for c, value in enumerate(values):
                self.sales_table.setItem(r, c, QTableWidgetItem(str(value or "")))


    def load_medicines(self):
        """Load/search the Inventory Control grid."""
        search = ""
        if hasattr(self, "inventory_search"):
            search = self.inventory_search.text().strip()

        con = sqlite3.connect(DB_NAME)
        con.row_factory = sqlite3.Row

        if search:
            value = f"%{search}%"
            rows = con.execute("""
                SELECT *
                FROM medicines
                WHERE barcode LIKE ?
                   OR name LIKE ?
                   OR generic_name LIKE ?
                   OR category LIKE ?
                ORDER BY id DESC
                LIMIT 500
            """, (value, value, value, value)).fetchall()
        else:
            rows = con.execute("""
                SELECT *
                FROM medicines
                ORDER BY id DESC
                LIMIT 500
            """).fetchall()

        # Category list for the editable combo box.
        categories = con.execute("""
            SELECT DISTINCT category
            FROM medicines
            WHERE TRIM(COALESCE(category, '')) <> ''
            ORDER BY category
        """).fetchall()

        con.close()

        if hasattr(self, "inv_category"):
            current_text = self.inv_category.currentText()
            self.inv_category.blockSignals(True)
            self.inv_category.clear()
            self.inv_category.addItem("")
            for category in categories:
                self.inv_category.addItem(str(category[0]))
            self.inv_category.setCurrentText(current_text)
            self.inv_category.blockSignals(False)

        self.medicine_table.setRowCount(0)

        for row in rows:
            r = self.medicine_table.rowCount()
            self.medicine_table.insertRow(r)

            keys = set(row.keys())
            values = [
                row["barcode"],
                row["name"],
                row["category"],
                row["stock"],
                f"{float(row['purchase_price'] or 0):,.2f}",
                f"{float(row['whole_sale_price'] or 0):,.2f}" if "whole_sale_price" in keys else "0.00",
                f"{float(row['sale_price'] or 0):,.2f}",
                row["batch_number"] if "batch_number" in keys else "",
                row["expiry_date"],
                row["location"] if "location" in keys else "",
                f"{float(row['tax_rate'] or 0):,.2f}" if "tax_rate" in keys else "0.00",
                row["reorder_level"] if "reorder_level" in keys else 0,
            ]

            for c, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                if c == 0:
                    item.setData(Qt.ItemDataRole.UserRole, int(row["id"]))
                self.medicine_table.setItem(r, c, item)

        self.refresh_inventory_summary()

    def refresh_inventory_summary(self):
        if not hasattr(self, "inv_in_hand"):
            return

        selected_id = getattr(self, "inventory_selected_id", None)

        con = sqlite3.connect(DB_NAME)

        if selected_id:
            row = con.execute("""
                SELECT stock, reorder_level
                FROM medicines
                WHERE id = ?
            """, (selected_id,)).fetchone()
            in_hand = int(row[0] or 0) if row else 0
            reorder_level = int(row[1] or 0) if row else 0

            today_purchase = con.execute("""
                SELECT COALESCE(SUM(quantity), 0)
                FROM purchases
                WHERE medicine_id = ?
                  AND date(created_at) = date('now', 'localtime')
            """, (selected_id,)).fetchone()[0]

            today_amount = con.execute("""
                SELECT COALESCE(SUM(total), 0)
                FROM purchases
                WHERE medicine_id = ?
                  AND date(created_at) = date('now', 'localtime')
            """, (selected_id,)).fetchone()[0]
        else:
            in_hand = con.execute("""
                SELECT COALESCE(SUM(stock), 0) FROM medicines
            """).fetchone()[0]

            reorder_level = con.execute("""
                SELECT COUNT(*)
                FROM medicines
                WHERE stock <= COALESCE(reorder_level, 0)
                  AND COALESCE(reorder_level, 0) > 0
            """).fetchone()[0]

            today_purchase = con.execute("""
                SELECT COALESCE(SUM(quantity), 0)
                FROM purchases
                WHERE date(created_at) = date('now', 'localtime')
            """).fetchone()[0]

            today_amount = con.execute("""
                SELECT COALESCE(SUM(total), 0)
                FROM purchases
                WHERE date(created_at) = date('now', 'localtime')
            """).fetchone()[0]

        con.close()

        self.inv_in_hand.setText(f"In Hand   {int(in_hand or 0)}")
        self.inv_today_purchase.setText(
            f"Today's Purchasing   {int(today_purchase or 0)}"
        )

        if selected_id:
            status_value = 1 if int(in_hand or 0) <= int(reorder_level or 0) and int(reorder_level or 0) > 0 else 0
        else:
            status_value = int(reorder_level or 0)

        self.inv_reorder_status.setText(f"Re Order   {status_value}")
        self.inv_invoice_amount.setText(
            f"Invoice Bill Amount   Rs. {float(today_amount or 0):,.2f}"
        )

    def inventory_selection_changed(self):
        selected = self.medicine_table.selectedItems()
        if not selected:
            return

        row_index = self.medicine_table.currentRow()
        code_item = self.medicine_table.item(row_index, 0)
        if code_item is None:
            return

        medicine_id = code_item.data(Qt.ItemDataRole.UserRole)
        if medicine_id is None:
            return

        con = sqlite3.connect(DB_NAME)
        con.row_factory = sqlite3.Row
        row = con.execute("""
            SELECT * FROM medicines WHERE id = ?
        """, (medicine_id,)).fetchone()
        con.close()

        if not row:
            return

        keys = set(row.keys())
        self.inventory_selected_id = int(row["id"])
        self.inv_item_code.setText(str(row["barcode"] or ""))
        self.inv_item_name.setText(str(row["name"] or ""))
        self.inv_category.setCurrentText(str(row["category"] or ""))
        self.inv_cost.setValue(float(row["purchase_price"] or 0))
        self.inv_retail.setValue(float(row["sale_price"] or 0))
        self.inv_wholesale.setValue(
            float(row["whole_sale_price"] or 0)
            if "whole_sale_price" in keys else 0
        )
        self.inv_tax.setValue(
            float(row["tax_rate"] or 0)
            if "tax_rate" in keys else 0
        )
        self.inv_opening_qty.setValue(int(row["stock"] or 0))
        self.inv_scheme.setText(
            str(row["scheme"] or "") if "scheme" in keys else ""
        )
        self.inv_reorder.setValue(
            int(row["reorder_level"] or 0)
            if "reorder_level" in keys else 0
        )
        self.inv_location.setText(
            str(row["location"] or "") if "location" in keys else ""
        )
        self.inv_batch.setText(
            str(row["batch_number"] or "") if "batch_number" in keys else ""
        )

        if row["expiry_date"]:
            qdate = QDate.fromString(str(row["expiry_date"]), "yyyy-MM-dd")
            if qdate.isValid():
                self.inv_expiry.setDate(qdate)

        self.refresh_inventory_summary()

    def clear_inventory_form(self):
        self.inventory_selected_id = None
        self.inv_item_code.clear()
        self.inv_item_name.clear()
        self.inv_category.setCurrentText("")
        self.inv_cost.setValue(0)
        self.inv_retail.setValue(0)
        self.inv_wholesale.setValue(0)
        try:
            self.inv_tax.setValue(float(get_setting("default_tax_rate", "0") or 0))
        except Exception:
            self.inv_tax.setValue(0)
        self.inv_opening_qty.setValue(0)
        self.inv_scheme.clear()
        self.inv_reorder.setValue(0)
        self.inv_location.clear()
        self.inv_batch.clear()
        self.inv_expiry.setDate(QDate.currentDate().addYears(1))
        self.medicine_table.clearSelection()
        self.refresh_inventory_summary()
        self.inv_item_code.setFocus()

    def save_inventory_item(self):
        name = self.inv_item_name.text().strip()
        barcode = self.inv_item_code.text().strip()

        if not name:
            QMessageBox.warning(
                self, "Required", "Item / medicine name is required."
            )
            self.inv_item_name.setFocus()
            return

        con = sqlite3.connect(DB_NAME)
        con.row_factory = sqlite3.Row

        if barcode:
            duplicate = con.execute("""
                SELECT id FROM medicines WHERE barcode = ?
            """, (barcode,)).fetchone()
            if duplicate:
                con.close()
                QMessageBox.warning(
                    self, "Duplicate Item Code",
                    "This item code / barcode already exists."
                )
                return

        expiry = self.inv_expiry.date().toString("yyyy-MM-dd")
        qty = self.inv_opening_qty.value()
        batch = self.inv_batch.text().strip() or "OPENING"

        cursor = con.execute("""
            INSERT INTO medicines (
                name, generic_name, barcode, category,
                purchase_price, sale_price, stock, expiry_date,
                created_at, whole_sale_price, tax_rate, scheme,
                reorder_level, location, batch_number
            )
            VALUES (?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            name,
            barcode,
            self.inv_category.currentText().strip(),
            self.inv_cost.value(),
            self.inv_retail.value(),
            qty,
            expiry,
            now_text(),
            self.inv_wholesale.value(),
            self.inv_tax.value(),
            self.inv_scheme.text().strip(),
            self.inv_reorder.value(),
            self.inv_location.text().strip(),
            batch,
        ))

        medicine_id = cursor.lastrowid

        if qty > 0:
            con.execute("""
                INSERT INTO medicine_batches (
                    medicine_id, supplier_id, batch_number, expiry_date,
                    purchase_price, sale_price, quantity_received,
                    quantity_available, created_at
                )
                VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?)
            """, (
                medicine_id,
                batch,
                expiry,
                self.inv_cost.value(),
                self.inv_retail.value(),
                qty,
                qty,
                now_text(),
            ))

        con.commit()
        con.close()

        QMessageBox.information(
            self, "Inventory Saved", "Inventory item saved successfully."
        )
        self.load_medicines()
        self.clear_inventory_form()

    def update_inventory_item(self):
        medicine_id = getattr(self, "inventory_selected_id", None)
        if not medicine_id:
            QMessageBox.warning(
                self, "Select Item", "Select an inventory item to update."
            )
            return

        name = self.inv_item_name.text().strip()
        barcode = self.inv_item_code.text().strip()

        if not name:
            QMessageBox.warning(self, "Required", "Item name is required.")
            return

        con = sqlite3.connect(DB_NAME)

        if barcode:
            duplicate = con.execute("""
                SELECT id FROM medicines
                WHERE barcode = ? AND id <> ?
            """, (barcode, medicine_id)).fetchone()
            if duplicate:
                con.close()
                QMessageBox.warning(
                    self, "Duplicate Item Code",
                    "This item code / barcode belongs to another item."
                )
                return

        old_stock = con.execute("""
            SELECT stock FROM medicines WHERE id = ?
        """, (medicine_id,)).fetchone()
        old_stock = int(old_stock[0] or 0) if old_stock else 0
        new_stock = self.inv_opening_qty.value()
        expiry = self.inv_expiry.date().toString("yyyy-MM-dd")
        batch = self.inv_batch.text().strip() or "OPENING"

        con.execute("""
            UPDATE medicines
            SET name = ?,
                barcode = ?,
                category = ?,
                purchase_price = ?,
                sale_price = ?,
                stock = ?,
                expiry_date = ?,
                whole_sale_price = ?,
                tax_rate = ?,
                scheme = ?,
                reorder_level = ?,
                location = ?,
                batch_number = ?
            WHERE id = ?
        """, (
            name,
            barcode,
            self.inv_category.currentText().strip(),
            self.inv_cost.value(),
            self.inv_retail.value(),
            new_stock,
            expiry,
            self.inv_wholesale.value(),
            self.inv_tax.value(),
            self.inv_scheme.text().strip(),
            self.inv_reorder.value(),
            self.inv_location.text().strip(),
            batch,
            medicine_id,
        ))

        difference = new_stock - old_stock
        existing_batch = con.execute("""
            SELECT id
            FROM medicine_batches
            WHERE medicine_id = ? AND batch_number = ?
        """, (medicine_id, batch)).fetchone()

        if existing_batch:
            con.execute("""
                UPDATE medicine_batches
                SET expiry_date = ?,
                    purchase_price = ?,
                    sale_price = ?,
                    quantity_available = MAX(0, quantity_available + ?)
                WHERE id = ?
            """, (
                expiry,
                self.inv_cost.value(),
                self.inv_retail.value(),
                difference,
                existing_batch[0],
            ))
        elif new_stock > 0:
            con.execute("""
                INSERT INTO medicine_batches (
                    medicine_id, supplier_id, batch_number, expiry_date,
                    purchase_price, sale_price, quantity_received,
                    quantity_available, created_at
                )
                VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?)
            """, (
                medicine_id,
                batch,
                expiry,
                self.inv_cost.value(),
                self.inv_retail.value(),
                new_stock,
                new_stock,
                now_text(),
            ))

        con.commit()
        con.close()

        QMessageBox.information(
            self, "Inventory Updated", "Inventory item updated successfully."
        )
        self.load_medicines()

    def delete_inventory_item(self):
        medicine_id = getattr(self, "inventory_selected_id", None)
        if not medicine_id:
            QMessageBox.warning(
                self, "Select Item", "Select an inventory item to delete."
            )
            return

        answer = QMessageBox.warning(
            self,
            "Delete Inventory Item",
            "Delete the selected item?\n\n"
            "Items already used in sales/purchases should normally be kept.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        con = sqlite3.connect(DB_NAME)

        used_purchase = con.execute("""
            SELECT COUNT(*) FROM purchases WHERE medicine_id = ?
        """, (medicine_id,)).fetchone()[0]

        # Sales table stores medicine name rather than medicine_id, so keep
        # historical records safe and block deletion if the item has purchases.
        if used_purchase:
            con.close()
            QMessageBox.warning(
                self,
                "Cannot Delete",
                "This item already has purchase history. "
                "Set its stock to 0 instead of deleting it."
            )
            return

        con.execute(
            "DELETE FROM medicine_batches WHERE medicine_id = ?",
            (medicine_id,)
        )
        con.execute(
            "DELETE FROM medicines WHERE id = ?",
            (medicine_id,)
        )
        con.commit()
        con.close()

        QMessageBox.information(
            self, "Deleted", "Inventory item deleted successfully."
        )
        self.clear_inventory_form()
        self.load_medicines()

    def update_default_inventory_tax(self):
        value, ok = QInputDialog.getDouble(
            self,
            "Default Tax Rate",
            "Default tax rate %:",
            float(get_setting("default_tax_rate", "0") or 0),
            0,
            100,
            2,
        )
        if not ok:
            return

        set_setting("default_tax_rate", value)
        self.inv_tax.setValue(value)
        QMessageBox.information(
            self, "Tax Updated", f"Default tax rate set to {value:.2f}%."
        )

    def import_inventory_stock(self):
        QMessageBox.information(
            self,
            "Import Stock",
            "CSV / Excel stock import will be added as a separate import step.\n\n"
            "For now, use this Inventory Control screen to add or update items."
        )

    def load_suppliers(self):
        con = sqlite3.connect(DB_NAME)
        con.row_factory = sqlite3.Row
        rows = con.execute("""
            SELECT * FROM suppliers ORDER BY id DESC
        """).fetchall()
        con.close()

        self.supplier_table.setRowCount(0)

        for row in rows:
            r = self.supplier_table.rowCount()
            self.supplier_table.insertRow(r)

            values = [
                row["id"], row["name"], row["company"], row["phone"], row["address"]
            ]

            for c, value in enumerate(values):
                self.supplier_table.setItem(r, c, QTableWidgetItem(str(value or "")))

    def load_purchases(self):
        con = sqlite3.connect(DB_NAME)
        con.row_factory = sqlite3.Row
        rows = con.execute("""
            SELECT
                p.invoice_number,
                s.name AS supplier,
                m.name AS medicine,
                p.batch_number,
                p.expiry_date,
                p.quantity,
                p.purchase_price,
                p.total,
                p.created_at
            FROM purchases p
            LEFT JOIN suppliers s ON s.id = p.supplier_id
            LEFT JOIN medicines m ON m.id = p.medicine_id
            ORDER BY p.id DESC
        """).fetchall()
        con.close()

        self.purchase_table.setRowCount(0)

        for row in rows:
            r = self.purchase_table.rowCount()
            self.purchase_table.insertRow(r)

            values = [
                row["invoice_number"], row["supplier"], row["medicine"],
                row["batch_number"], row["expiry_date"], row["quantity"],
                f"Rs. {row['purchase_price']:,.2f}",
                f"Rs. {row['total']:,.2f}", row["created_at"]
            ]

            for c, value in enumerate(values):
                self.purchase_table.setItem(r, c, QTableWidgetItem(str(value or "")))

    def load_stock(self):
        con = sqlite3.connect(DB_NAME)
        con.row_factory = sqlite3.Row
        rows = con.execute("""
            SELECT
                m.name AS medicine,
                b.batch_number,
                s.name AS supplier,
                b.expiry_date,
                b.purchase_price,
                b.sale_price,
                b.quantity_received,
                b.quantity_available
            FROM medicine_batches b
            LEFT JOIN medicines m ON m.id = b.medicine_id
            LEFT JOIN suppliers s ON s.id = b.supplier_id
            ORDER BY b.expiry_date ASC, b.id ASC
        """).fetchall()
        con.close()

        self.stock_table.setRowCount(0)

        for row in rows:
            r = self.stock_table.rowCount()
            self.stock_table.insertRow(r)

            values = [
                row["medicine"], row["batch_number"],
                row["supplier"] or "Opening Stock", row["expiry_date"],
                f"Rs. {row['purchase_price']:,.2f}",
                f"Rs. {row['sale_price']:,.2f}",
                row["quantity_received"], row["quantity_available"]
            ]

            for c, value in enumerate(values):
                self.stock_table.setItem(r, c, QTableWidgetItem(str(value or "")))

    def load_expiry_alerts(self):
        mode = self.expiry_filter.currentText()

        if mode == "Expired":
            where = "date(b.expiry_date) < date('now')"
        elif mode == "Next 30 Days":
            where = "date(b.expiry_date) BETWEEN date('now') AND date('now', '+30 day')"
        elif mode == "Next 60 Days":
            where = "date(b.expiry_date) BETWEEN date('now') AND date('now', '+60 day')"
        elif mode == "Next 90 Days":
            where = "date(b.expiry_date) BETWEEN date('now') AND date('now', '+90 day')"
        else:
            where = "1=1"

        con = sqlite3.connect(DB_NAME)
        con.row_factory = sqlite3.Row

        rows = con.execute(f"""
            SELECT
                m.name AS medicine,
                b.batch_number,
                s.name AS supplier,
                b.expiry_date,
                b.quantity_available,
                b.sale_price,
                CASE
                    WHEN date(b.expiry_date) < date('now') THEN 'EXPIRED'
                    WHEN date(b.expiry_date) <= date('now', '+30 day') THEN '30 DAYS'
                    WHEN date(b.expiry_date) <= date('now', '+60 day') THEN '60 DAYS'
                    WHEN date(b.expiry_date) <= date('now', '+90 day') THEN '90 DAYS'
                    ELSE 'OK'
                END AS status
            FROM medicine_batches b
            LEFT JOIN medicines m ON m.id = b.medicine_id
            LEFT JOIN suppliers s ON s.id = b.supplier_id
            WHERE b.quantity_available > 0
            AND {where}
            ORDER BY date(b.expiry_date) ASC
        """).fetchall()

        con.close()

        self.expiry_table.setRowCount(0)

        for row in rows:
            r = self.expiry_table.rowCount()
            self.expiry_table.insertRow(r)

            values = [
                row["medicine"], row["batch_number"],
                row["supplier"] or "Opening Stock", row["expiry_date"],
                row["quantity_available"], f"Rs. {row['sale_price']:,.2f}",
                row["status"]
            ]

            for c, value in enumerate(values):
                self.expiry_table.setItem(r, c, QTableWidgetItem(str(value or "")))

    def load_returns(self):
        con = sqlite3.connect(DB_NAME)
        con.row_factory = sqlite3.Row

        rows = con.execute("""
            SELECT
                return_number, invoice, medicine, quantity,
                refund_amount, reason, created_at
            FROM sales_returns
            ORDER BY id DESC
        """).fetchall()

        con.close()

        self.return_table.setRowCount(0)

        for row in rows:
            r = self.return_table.rowCount()
            self.return_table.insertRow(r)

            values = [
                row["return_number"], row["invoice"], row["medicine"],
                row["quantity"], f"Rs. {row['refund_amount']:,.2f}",
                row["reason"], row["created_at"]
            ]

            for c, value in enumerate(values):
                self.return_table.setItem(r, c, QTableWidgetItem(str(value or "")))

    def load_customers(self):
        con = sqlite3.connect(DB_NAME)
        con.row_factory = sqlite3.Row
        rows = con.execute("""
            SELECT id, name, phone, address, created_at
            FROM customers
            ORDER BY id DESC
        """).fetchall()
        con.close()

        self.customer_table.setRowCount(0)
        for row in rows:
            r = self.customer_table.rowCount()
            self.customer_table.insertRow(r)
            values = [
                row["id"], row["name"], row["phone"],
                row["address"], row["created_at"]
            ]
            for c, value in enumerate(values):
                self.customer_table.setItem(
                    r, c, QTableWidgetItem(str(value or ""))
                )

    def load_expenses(self):
        con = sqlite3.connect(DB_NAME)
        con.row_factory = sqlite3.Row

        rows = con.execute("""
            SELECT id, category, description, amount, expense_date, created_at
            FROM expenses
            ORDER BY expense_date DESC, id DESC
        """).fetchall()

        total = con.execute("""
            SELECT COALESCE(SUM(amount), 0)
            FROM expenses
        """).fetchone()[0]

        con.close()

        self.expense_total_label.setText(f"Total: Rs. {float(total or 0):,.2f}")
        self.expense_table.setRowCount(0)

        for row in rows:
            r = self.expense_table.rowCount()
            self.expense_table.insertRow(r)

            values = [
                row["id"], row["category"], row["description"],
                f"Rs. {row['amount']:,.2f}", row["expense_date"], row["created_at"]
            ]

            for c, value in enumerate(values):
                self.expense_table.setItem(
                    r, c, QTableWidgetItem(str(value or ""))
                )

    def set_report_period(self, code):
        today = QDate.currentDate()

        if code == "today":
            start = today
            end = today
        elif code == "yesterday":
            start = today.addDays(-1)
            end = start
        elif code == "week":
            start = today.addDays(-(today.dayOfWeek() - 1))
            end = today
        elif code == "month":
            start = QDate(today.year(), today.month(), 1)
            end = today
        elif code == "last_month":
            first_this = QDate(today.year(), today.month(), 1)
            end = first_this.addDays(-1)
            start = QDate(end.year(), end.month(), 1)
        elif code == "year":
            start = QDate(today.year(), 1, 1)
            end = today
        else:
            start = QDate(today.year(), today.month(), 1)
            end = today

        self.report_from.setDate(start)
        self.report_to.setDate(end)
        self.load_reports()

    def open_dashboard_report(self, report_type):
        self.show_reports()
        if hasattr(self, "report_type"):
            index = self.report_type.findText(report_type)
            if index >= 0:
                self.report_type.setCurrentIndex(index)
        self.set_report_period("today")

    def load_reports(self):
        from_date = self.report_from.date().toString("yyyy-MM-dd")
        to_date = self.report_to.date().toString("yyyy-MM-dd")

        if from_date > to_date:
            QMessageBox.warning(self, "Date Range", "From date cannot be after To date.")
            return

        report_type = self.report_type.currentText() if hasattr(self, "report_type") else "Sales"

        con = sqlite3.connect(DB_NAME)
        con.row_factory = sqlite3.Row

        gross_sales = float(con.execute("""
            SELECT COALESCE(SUM(total), 0)
            FROM sales
            WHERE date(created_at) BETWEEN ? AND ?
        """, (from_date, to_date)).fetchone()[0] or 0)

        returns_total = float(con.execute("""
            SELECT COALESCE(SUM(refund_amount), 0)
            FROM sales_returns
            WHERE date(created_at) BETWEEN ? AND ?
        """, (from_date, to_date)).fetchone()[0] or 0)

        purchases_total = float(con.execute("""
            SELECT COALESCE(SUM(total), 0)
            FROM purchases
            WHERE date(created_at) BETWEEN ? AND ?
        """, (from_date, to_date)).fetchone()[0] or 0)

        expenses_total = float(con.execute("""
            SELECT COALESCE(SUM(amount), 0)
            FROM expenses
            WHERE date(expense_date) BETWEEN ? AND ?
        """, (from_date, to_date)).fetchone()[0] or 0)

        # Cost of goods sold from the exact batches allocated to sold items.
        cogs = float(con.execute("""
            SELECT COALESCE(SUM(a.quantity * b.purchase_price), 0)
            FROM sale_batch_allocations a
            JOIN medicine_batches b ON b.id = a.batch_id
            WHERE EXISTS (
                SELECT 1
                FROM sales s
                WHERE s.invoice = a.invoice
                  AND date(s.created_at) BETWEEN ? AND ?
            )
        """, (from_date, to_date)).fetchone()[0] or 0)

        net_sales = gross_sales - returns_total
        profit_loss = net_sales - cogs - expenses_total

        self.report_gross_sales.value_label.setText(f"Rs. {gross_sales:,.0f}")
        self.report_returns.value_label.setText(f"Rs. {returns_total:,.0f}")
        self.report_net_sales.value_label.setText(f"Rs. {net_sales:,.0f}")
        self.report_cogs.value_label.setText(f"Rs. {cogs:,.0f}")
        self.report_expenses.value_label.setText(f"Rs. {expenses_total:,.0f}")
        self.report_profit_loss.value_label.setText(f"Rs. {profit_loss:,.0f}")

        self.report_context_label.setText(
            f"{report_type} Report  |  {self.report_from.date().toString('dd-MM-yyyy')} "
            f"to {self.report_to.date().toString('dd-MM-yyyy')}"
        )

        if report_type == "Sales":
            rows = con.execute("""
                SELECT
                    s.invoice,
                    COUNT(*) AS items,
                    SUM(s.quantity) AS qty,
                    SUM(s.total) AS gross,
                    COALESCE((
                        SELECT SUM(sr.refund_amount)
                        FROM sales_returns sr
                        WHERE sr.invoice = s.invoice
                    ), 0) AS returned,
                    COALESCE((
                        SELECT p.payment_method
                        FROM payments p
                        WHERE p.invoice = s.invoice
                        ORDER BY p.id DESC LIMIT 1
                    ), '') AS payment_method,
                    MAX(s.created_at) AS created_at
                FROM sales s
                WHERE date(s.created_at) BETWEEN ? AND ?
                GROUP BY s.invoice
                ORDER BY MAX(s.id) DESC
            """, (from_date, to_date)).fetchall()

            headers = ["Invoice", "Items", "Qty", "Gross", "Returned", "Net", "Payment / Date"]
            values_rows = []
            for row in rows:
                returned = float(row["returned"] or 0)
                gross = float(row["gross"] or 0)
                values_rows.append([
                    row["invoice"], row["items"], row["qty"],
                    f"Rs. {gross:,.2f}", f"Rs. {returned:,.2f}",
                    f"Rs. {gross-returned:,.2f}",
                    f"{row['payment_method']} / {row['created_at']}"
                ])

        elif report_type == "Expenses":
            rows = con.execute("""
                SELECT id, category, description, amount, expense_date, created_at
                FROM expenses
                WHERE date(expense_date) BETWEEN ? AND ?
                ORDER BY date(expense_date) DESC, id DESC
            """, (from_date, to_date)).fetchall()
            headers = ["ID", "Category", "Description", "Amount", "Expense Date", "Created"]
            values_rows = [[
                r["id"], r["category"], r["description"],
                f"Rs. {float(r['amount'] or 0):,.2f}", r["expense_date"], r["created_at"]
            ] for r in rows]

        elif report_type == "Purchases":
            rows = con.execute("""
                SELECT p.invoice_number, COALESCE(s.name, '') supplier,
                       COALESCE(m.name, '') medicine, p.batch_number,
                       p.quantity, p.purchase_price, p.total, p.created_at
                FROM purchases p
                LEFT JOIN suppliers s ON s.id = p.supplier_id
                LEFT JOIN medicines m ON m.id = p.medicine_id
                WHERE date(p.created_at) BETWEEN ? AND ?
                ORDER BY p.id DESC
            """, (from_date, to_date)).fetchall()
            headers = ["Invoice", "Supplier", "Medicine", "Batch", "Qty", "Cost", "Total", "Date"]
            values_rows = [[
                r["invoice_number"], r["supplier"], r["medicine"], r["batch_number"],
                r["quantity"], f"Rs. {float(r['purchase_price'] or 0):,.2f}",
                f"Rs. {float(r['total'] or 0):,.2f}", r["created_at"]
            ] for r in rows]

        elif report_type == "Stock":
            rows = con.execute("""
                SELECT id, name, generic_name, category, stock,
                       purchase_price, sale_price, expiry_date
                FROM medicines
                ORDER BY name
            """).fetchall()
            headers = ["ID", "Medicine", "Generic", "Category", "Stock", "Purchase", "Sale", "Expiry"]
            values_rows = [[
                r["id"], r["name"], r["generic_name"], r["category"], r["stock"],
                f"Rs. {float(r['purchase_price'] or 0):,.2f}",
                f"Rs. {float(r['sale_price'] or 0):,.2f}", r["expiry_date"]
            ] for r in rows]

        elif report_type == "Profit & Loss":
            headers = ["Metric", "Amount"]
            values_rows = [
                ["Gross Sales", f"Rs. {gross_sales:,.2f}"],
                ["Returns", f"Rs. {returns_total:,.2f}"],
                ["Net Sales", f"Rs. {net_sales:,.2f}"],
                ["Cost of Goods Sold", f"Rs. {cogs:,.2f}"],
                ["Gross Profit", f"Rs. {net_sales-cogs:,.2f}"],
                ["Operating Expenses", f"Rs. {expenses_total:,.2f}"],
                ["NET PROFIT / LOSS", f"Rs. {profit_loss:,.2f}"],
            ]

        else:
            # Credit ledger is reserved for the Payable/Receivable module.
            headers = ["Status", "Amount", "Note"]
            values_rows = [[
                report_type,
                "Rs. 0.00",
                "No credit-ledger entries recorded yet."
            ]]

        con.close()

        self.report_table.clear()
        self.report_table.setColumnCount(len(headers))
        self.report_table.setHorizontalHeaderLabels(headers)
        setup_table(self.report_table)
        self.report_table.setRowCount(0)

        for values in values_rows:
            r = self.report_table.rowCount()
            self.report_table.insertRow(r)
            for c, value in enumerate(values):
                self.report_table.setItem(r, c, QTableWidgetItem(str(value or "")))


    def load_sales_history(self):
        search = self.sales_history_search.text().strip()
        from_date = self.sales_history_from.date().toString("yyyy-MM-dd")
        to_date = self.sales_history_to.date().toString("yyyy-MM-dd")

        if from_date > to_date:
            QMessageBox.warning(self, "Date Range", "From date cannot be after To date.")
            return

        con = sqlite3.connect(DB_NAME)
        con.row_factory = sqlite3.Row

        params = [from_date, to_date]
        extra = ""

        if search:
            value = f"%{search}%"
            extra = """
                AND (
                    s.invoice LIKE ?
                    OR s.medicine LIKE ?
                    OR COALESCE(p.payment_method, '') LIKE ?
                )
            """
            params.extend([value, value, value])

        rows = con.execute(f"""
            SELECT
                s.invoice,
                COUNT(*) AS items,
                SUM(s.quantity) AS qty,
                SUM(s.total) AS gross,
                COALESCE((
                    SELECT SUM(sr.refund_amount)
                    FROM sales_returns sr
                    WHERE sr.invoice = s.invoice
                ), 0) AS returned,
                COALESCE(p.payment_method, '') AS payment_method,
                MAX(s.created_at) AS created_at
            FROM sales s
            LEFT JOIN payments p ON p.invoice = s.invoice
            WHERE date(s.created_at) BETWEEN ? AND ?
            {extra}
            GROUP BY s.invoice
            ORDER BY MAX(s.id) DESC
            LIMIT 500
        """, params).fetchall()

        con.close()

        self.sales_history_table.setRowCount(0)

        for row in rows:
            r = self.sales_history_table.rowCount()
            self.sales_history_table.insertRow(r)

            gross = float(row["gross"] or 0)
            returned = float(row["returned"] or 0)
            net = gross - returned

            values = [
                row["invoice"],
                row["items"],
                row["qty"],
                f"Rs. {gross:,.2f}",
                f"Rs. {returned:,.2f}",
                f"Rs. {net:,.2f}",
                row["payment_method"],
                row["created_at"]
            ]

            for c, value in enumerate(values):
                self.sales_history_table.setItem(
                    r, c, QTableWidgetItem(str(value or ""))
                )

        if rows:
            self.sales_history_table.selectRow(0)

    def selected_sales_history_invoice(self):
        row = self.sales_history_table.currentRow()

        if row < 0:
            QMessageBox.warning(self, "Select Invoice", "Select an invoice first.")
            return None

        item = self.sales_history_table.item(row, 0)
        return item.text().strip() if item else None

    def open_selected_old_receipt(self, *args):
        invoice = self.selected_sales_history_invoice()

        if not invoice:
            return

        con = sqlite3.connect(DB_NAME)
        con.row_factory = sqlite3.Row

        sales = con.execute("""
            SELECT medicine, quantity, total
            FROM sales
            WHERE invoice = ?
            ORDER BY id
        """, (invoice,)).fetchall()

        payment = con.execute("""
            SELECT received, change_amount, payment_method
            FROM payments
            WHERE invoice = ?
            ORDER BY id DESC
            LIMIT 1
        """, (invoice,)).fetchone()

        con.close()

        if not sales:
            QMessageBox.warning(self, "Not Found", "Invoice was not found.")
            return

        cart = []

        for row in sales:
            qty = int(row["quantity"] or 0)
            total = float(row["total"] or 0)
            price = total / qty if qty else 0

            cart.append({
                "name": row["medicine"],
                "qty": qty,
                "price": price
            })

        total = sum(float(row["total"] or 0) for row in sales)
        received = float(payment["received"] or 0) if payment else total
        change = float(payment["change_amount"] or 0) if payment else 0
        payment_method = payment["payment_method"] if payment else "Cash"

        dialog = ReceiptDialog(
            invoice,
            cart,
            total,
            received,
            change,
            payment_method,
            self
        )
        dialog.exec()

    def print_selected_old_receipt(self):
        invoice = self.selected_sales_history_invoice()

        if invoice:
            print_receipt_invoice(self, invoice)

    def load_users(self):
        con = sqlite3.connect(DB_NAME)
        con.row_factory = sqlite3.Row

        rows = con.execute("""
            SELECT id, username, full_name, role, active, created_at
            FROM users
            ORDER BY id
        """).fetchall()

        con.close()

        self.users_table.setRowCount(0)

        for row in rows:
            r = self.users_table.rowCount()
            self.users_table.insertRow(r)

            values = [
                row["id"],
                row["username"],
                row["full_name"],
                row["role"],
                "Active" if row["active"] else "Inactive",
                row["created_at"]
            ]

            for c, value in enumerate(values):
                self.users_table.setItem(
                    r, c, QTableWidgetItem(str(value or ""))
                )

    def load_settings(self):
        self.settings_pharmacy_name.setText(
            get_setting("pharmacy_name", "PHARMACY POS")
        )
        self.settings_address.setText(
            get_setting("address", "")
        )
        self.settings_phone.setText(
            get_setting("phone", "")
        )
        self.settings_receipt_footer.setText(
            get_setting("receipt_footer", "Thank you for your purchase.")
        )

        try:
            limit = int(get_setting("low_stock_limit", "10"))
        except ValueError:
            limit = 10

        self.settings_low_stock.setValue(max(1, limit))
        if hasattr(self, "settings_receipt_width"):
            paper = get_setting("receipt_paper_width", "80")
            self.settings_receipt_width.setCurrentText("58 mm" if str(paper).startswith("58") else "80 mm")

    def save_settings(self):
        set_setting(
            "pharmacy_name",
            self.settings_pharmacy_name.text().strip() or "PHARMACY POS"
        )
        set_setting(
            "address",
            self.settings_address.text().strip()
        )
        set_setting(
            "phone",
            self.settings_phone.text().strip()
        )
        set_setting(
            "receipt_footer",
            self.settings_receipt_footer.text().strip()
        )
        set_setting(
            "low_stock_limit",
            self.settings_low_stock.value()
        )
        if hasattr(self, "settings_receipt_width"):
            set_setting("receipt_paper_width", "58" if self.settings_receipt_width.currentText().startswith("58") else "80")

        self.setWindowTitle(
            get_setting("pharmacy_name", "PHARMACY POS")
        )

        QMessageBox.information(
            self,
            "Settings Saved",
            "Settings saved successfully."
        )

        self.refresh_dashboard()

    def create_database_backup(self):
        suggested = (
            "pharmacy_backup_"
            + datetime.now().strftime("%Y%m%d_%H%M%S")
            + ".db"
        )

        suggested_path = os.path.join(BACKUP_DIR, suggested)

        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save Database Backup",
            suggested_path,
            "Database Files (*.db);;All Files (*)"
        )

        if not filename:
            return

        if not filename.lower().endswith(".db"):
            filename += ".db"

        try:
            source = os.path.abspath(DB_NAME)
            destination = os.path.abspath(filename)

            if source == destination:
                QMessageBox.warning(
                    self,
                    "Invalid Location",
                    "Backup file must be different from the live pharmacy.db file."
                )
                return

            shutil.copy2(source, destination)

            QMessageBox.information(
                self,
                "Backup Completed",
                f"Database backup created successfully.\\n\\n{destination}"
            )

        except Exception as error:
            QMessageBox.critical(self, "Backup Failed", str(error))

    def restore_database_backup(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Select Database Backup",
            BACKUP_DIR,
            "Database Files (*.db);;All Files (*)"
        )

        if not filename:
            return

        answer = QMessageBox.warning(
            self,
            "Restore Backup",
            "This will replace the current pharmacy database.\\n\\n"
            "A safety backup of the current database will be created first.\\n\\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            live_db = os.path.abspath(DB_NAME)

            safety_name = os.path.join(
                BACKUP_DIR,
                "pharmacy_before_restore_"
                + datetime.now().strftime("%Y%m%d_%H%M%S")
                + ".db"
            )

            shutil.copy2(live_db, safety_name)
            shutil.copy2(filename, live_db)

            QMessageBox.information(
                self,
                "Restore Completed",
                "Backup restored successfully.\\n\\n"
                "Please close and reopen Pharmacy POS now."
            )

        except Exception as error:
            QMessageBox.critical(self, "Restore Failed", str(error))

    def prepare_fresh_database_copy(self):
        """
        Creates a blank database file for giving the same software to a new pharmacy.
        It does NOT touch the current pharmacy database.
        """
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save Fresh Pharmacy Database",
            "pharmacy_new.db",
            "Database Files (*.db)"
        )

        if not filename:
            return

        if not filename.lower().endswith(".db"):
            filename += ".db"

        try:
            if os.path.exists(filename):
                os.remove(filename)

            temp_con = sqlite3.connect(filename)

            # Clone schema only from the current database.
            source_con = sqlite3.connect(DB_NAME)

            schema_rows = source_con.execute("""
                SELECT sql
                FROM sqlite_master
                WHERE type = 'table'
                  AND sql IS NOT NULL
                  AND name NOT LIKE 'sqlite_%'
            """).fetchall()

            for row in schema_rows:
                temp_con.execute(row[0])

            source_con.close()

            # Basic blank settings.
            blank_settings = {
                "pharmacy_name": "PHARMACY POS",
                "address": "",
                "phone": "",
                "receipt_footer": "Thank you for your purchase.",
                "low_stock_limit": "10",
                "setup_completed": "0"
            }

            for key, value in blank_settings.items():
                temp_con.execute("""
                    INSERT INTO settings (key, value)
                    VALUES (?, ?)
                """, (key, value))

            salt, password_hash = hash_password("admin123")

            temp_con.execute("""
                INSERT INTO users (
                    username, full_name, role,
                    password_salt, password_hash,
                    active, created_at
                )
                VALUES ('admin', 'Administrator', 'Admin', ?, ?, 1, ?)
            """, (salt, password_hash, now_text()))

            temp_con.commit()
            temp_con.close()

            QMessageBox.information(
                self,
                "Fresh Database Created",
                "Fresh database created successfully.\\n\\n"
                "Use it only for a NEW pharmacy."
            )

        except Exception as error:
            QMessageBox.critical(self, "Create Failed", str(error))

    def open_data_folder(self):
        try:
            os.startfile(MOB_ROOT)
        except Exception as error:
            QMessageBox.critical(self, "Open Folder Failed", str(error))

    def apply_style(self):
        self.setStyleSheet("""
            * {
                font-family: "Segoe UI", Arial, sans-serif;
                font-size: 11px;
                color: #344255;
            }
            QMainWindow, #pharmaContent, #pharmaDashboard {
                background: #f4f7f9;
            }
            #pharmaSidebar {
                background: #2f4058;
                border: none;
            }
            #pharmaBrand {
                background: #2b3b50;
                border-bottom: 1px solid #42546b;
            }
            #pharmaBrandTitle {
                color: white;
                font-size: 18px;
                font-weight: 800;
            }
            #pharmaUserName {
                color: white;
                font-size: 11px;
                font-weight: 700;
                padding-top: 8px;
            }
            #pharmaOnline {
                color: #2ec4b6;
                font-size: 10px;
            }
            #pharmaNavButton {
                background: transparent;
                color: #dce5ee;
                border: none;
                border-left: 4px solid transparent;
                text-align: left;
                padding: 9px 15px;
                min-height: 18px;
            }
            #pharmaNavButton:hover {
                background: #3a5069;
                color: white;
                border-left: 4px solid #2ec4b6;
            }
            #pharmaSideLogout {
                margin: 8px 14px;
                background: #243447;
                color: white;
                border: 1px solid #42546b;
                border-radius: 3px;
                padding: 8px;
                font-weight: 700;
            }
            #pharmaSidebarFooter {
                color: #90a0b3;
                font-size: 9px;
                padding: 5px;
            }
            #pharmaTopbar {
                background: white;
                border-bottom: 1px solid #e2e8ee;
            }
            #pharmaPageTitle {
                color: #2d3e52;
                font-size: 18px;
                font-weight: 800;
            }
            #pharmaQuickButton {
                background: white;
                color: #37aa9c;
                border: 1px solid #bce1dc;
                border-radius: 2px;
                padding: 6px 9px;
                font-size: 9px;
                font-weight: 700;
            }
            #pharmaQuickButton:hover {
                background: #eaf9f6;
            }
            #pharmaBreadcrumb {
                color: #9aa7b5;
                font-size: 9px;
            }
            #pharmaWhiteCard {
                background: white;
                border: 1px solid #e1e8ee;
                border-radius: 4px;
            }
            #pharmaCardHeading {
                color: #35465a;
                font-size: 12px;
                font-weight: 800;
            }
            #pharmaTodayReport {
                color: #536273;
                background: white;
                padding: 8px;
            }
            QTableWidget {
                background: white;
                alternate-background-color: #f8fafb;
                border: 1px solid #e3e8ed;
                gridline-color: #eef2f5;
            }
            QHeaderView::section {
                background: #f5f7f9;
                color: #445366;
                border: none;
                border-bottom: 1px solid #dfe5ea;
                padding: 7px;
                font-weight: 700;
            }
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {
                background: white;
                border: 1px solid #d8e0e7;
                border-radius: 3px;
                padding: 6px 8px;
            }
            #inventoryHeader {
                background: #2f4058;
                border-radius: 4px;
            }
            #inventoryTitle {
                color: white;
                font-size: 18px;
                font-weight: 900;
            }
            #inventoryHeaderButton {
                background: white;
                color: #344255;
                border: 1px solid #d7e0e7;
                padding: 6px 10px;
            }
            #categoryAddButton {
                background: #2ec4b6;
                color: white;
                border: none;
                min-width: 30px;
                min-height: 30px;
                font-weight: 900;
            }


            #reportStatCard {
                background: white;
                border: 1px solid #e1e8ee;
                border-radius: 4px;
            }
            #reportStatTitle {
                color: #64748b;
                font-size: 10px;
                font-weight: 700;
            }
            #reportStatValue {
                color: #0f766e;
                font-size: 19px;
                font-weight: 900;
            }
            #reportStatSubtitle {
                color: #94a3b8;
                font-size: 9px;
            }
            #dashboardMetricValue {
                color: white;
                font-size: 17px;
                font-weight: 900;
            }
            #dashboardMetricTitle {
                color: white;
                font-size: 10px;
                font-weight: 800;
            }
            #dashboardMetricSubtitle {
                color: rgba(255,255,255,0.85);
                font-size: 8px;
            }
            #posGrandTotal {
                color: #19a187;
                font-size: 24px;
                font-weight: 900;
            }
        """)



DIALOG_STYLE = """
    QDialog { background: #f8fafc; }
    #dialogTitle {
        font-size: 24px; font-weight: 800; color: #111827;
    }
    #dialogSubtitle { color: #64748b; margin-bottom: 10px; }
    #bigTotal { font-size: 18px; font-weight: 800; color: #111827; }
    QLineEdit, QDoubleSpinBox, QSpinBox, QDateEdit, QComboBox {
        min-height: 38px; border: 1px solid #cbd5e1;
        border-radius: 7px; padding: 0 10px;
        background: white; font-size: 13px;
    }
    QTextEdit {
        background: white; border: 1px solid #cbd5e1;
        border-radius: 8px; padding: 12px;
        font-family: Consolas; font-size: 13px;
    }
    #primaryButton {
        background: #2563eb; color: white; border: none;
        padding: 11px 20px; border-radius: 8px; font-weight: 700;
    }
    #secondaryButton {
        background: #e5e7eb; color: #111827; border: none;
        padding: 11px 20px; border-radius: 8px; font-weight: 700;
    }
    #completeSaleButton {
        min-height: 48px;
        background: #059669;
        color: white;
        border: none;
        border-radius: 9px;
        font-size: 15px;
        font-weight: 900;
    }
"""


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    structure_ok, structure_error = ensure_mob_structure()

    if not structure_ok:
        QMessageBox.critical(
            None,
            "D:\\MOB Setup Error",
            "Pharmacy POS requires:\\n\\n"
            "D:\\MOB\\n\\n"
            "Windows could not create/access this folder.\\n\\n"
            + structure_error
        )
        sys.exit(1)

    migrate_legacy_database_to_mob()
    init_database()
    sync_config_files_from_database()

    if os.path.exists(APP_ICON_FILE):
        app.setWindowIcon(QIcon(APP_ICON_FILE))

    enter_filter = EnterNavigationFilter(app)
    app.installEventFilter(enter_filter)

    launcher = LauncherDialog()

    if launcher.exec() != QDialog.DialogCode.Accepted:
        sys.exit(0)

    window = PharmacyPOS(launcher.user)
    window.show()

    sys.exit(app.exec())
