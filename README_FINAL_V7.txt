PHARMACY POS v7.0 FINAL - ROLE PROTECTED

USER ACCESS
===========
ADMIN
- Full access to the complete software.
- Dashboard, reports, profit/loss, purchases, stock, suppliers,
  customers, returns, expenses, expiry alerts, users, settings,
  admin center, barcode management and all inventory actions.

CASHIER / COUNTER USER
- Invoice / POS Billing ONLY.
- Inventory Add/Search ONLY.
- Can create a new medicine/inventory item.
- Cannot update/delete existing inventory items.
- Cannot use reports, profit/loss, purchase, stock administration,
  suppliers, expenses, users, settings, Admin Center or other
  protected modules.
- After login, opens directly on POS Billing.
- Keyboard shortcuts are restricted too:
    F2 = POS
    F3 = Inventory Add
    F10 = Complete Sale
    Ctrl+P = context print

OTHER CURRENT FEATURES RETAINED
===============================
- Machine-locked license system.
- 3 Inch / 80mm thermal receipt support.
- 58mm/A4 options.
- Exact barcode label preset:
  1.5 x 1.10 inch = 38.10 x 27.94 mm.
- Barcode Management for Admin.
- Report printing for Admin.
- Expiry handling.
- Keyboard-first billing.
- Amount Received + Enter flow.
- POS stays open after each bill.
- Customer editable:
    D:\MOB\Config\business.txt
    D:\MOB\Assets\receipt_logo.png
    D:\MOB\Support\footer.txt
- Protected receipt/report developer line:
    POS Software by Wabwar | 03166965457

NETWORKING NOTE
===============
The Admin Center contains Counter/Network settings, but production
multi-PC central-database networking is NOT implemented in this build.
Do not share the SQLite database directly between PCs.
A later central MySQL/SQL Server migration is required for true
multi-counter simultaneous operation.

INSTALL / TEST
==============
1. Copy main.py to D:\MOB\App\main.py
2. Copy business.txt to D:\MOB\Config\business.txt
3. Copy footer.txt to D:\MOB\Support\footer.txt
4. Keep receipt_logo.png at D:\MOB\Assets\receipt_logo.png
5. Run:
   cd /d D:\MOB\App
   python main.py

TEST BOTH:
- Admin login: full access.
- Cashier login: only Invoice/POS + Inventory Add.
