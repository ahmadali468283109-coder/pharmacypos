Pharmacy POS v6.5 FINAL

Fixes:
- Fixed barcode printing QPageSize constructor error in PyQt6.
- Fixed the same custom-page-size construction for thermal receipt/report printing.
- Exact barcode default remains:
  1.5 x 1.10 inch = 38.10 x 27.94 mm
- 3 Inch / 80 mm thermal receipt default remains.
- All v6.4 features retained.

Install:
1. Copy main.py to D:\MOB\App\main.py
2. Run:
   cd /d D:\MOB\App
   python main.py
3. Open Admin > Barcode Management.
4. Select the actual barcode printer (not OneNote).
5. Print one test label first.
