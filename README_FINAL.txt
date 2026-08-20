PHARMACY POS v6.4 FINAL STABLE

THIS IS THE SINGLE VERSION TO USE.

INCLUDED:
- Existing working POS, inventory, purchases, stock, suppliers/manufacturers,
  customers, returns, expenses, users, settings and license system
- Reference-style dashboard and reports
- Clickable dashboard report cards
- Profit & Loss reports
- Report filters
- Report printing
- 3 Inch / 80mm thermal receipt default
- 58mm and A4 options
- Safe receipt printer selection
- Admin Center
- POS Settings
- Counter / Network settings screen
- Shortcut keys
- Barcode Management
- Exact default barcode label:
  1.5 x 1.10 inch = 38.10 x 27.94 mm
- Barcode preview and printing
- Product name below barcode
- Optional price on barcode
- Multiple barcode label quantity
- Expiry alerts / expired batch sale blocking
- Customer editable branding:
  D:\MOB\Config\business.txt
  D:\MOB\Assets\receipt_logo.png
  D:\MOB\Support\footer.txt
- Protected permanent developer line:
  POS Software by Wabwar | 03166965457

INSTALL:
1. Extract this ZIP.
2. Copy main.py to:
   D:\MOB\App\main.py
3. Copy business.txt to:
   D:\MOB\Config\business.txt
4. Copy footer.txt to:
   D:\MOB\Support\footer.txt
5. Keep your logo at:
   D:\MOB\Assets\receipt_logo.png
6. Run:
   cd /d D:\MOB\App
   python main.py

IMPORTANT:
- This package fixes both previous runtime import problems:
  QShortcut and QTabWidget.
- Python syntax was validated.
- All Q-prefixed PyQt symbols used in the file were statically checked
  against the import list.
- Multi-counter CENTRAL DATABASE networking is not implemented yet.
  Do not share the SQLite DB directly across PCs.
