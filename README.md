# 🌾 ChakkiMate (चक्कीमेट)
### The Ultimate Flour Mill & Grain Processing Management System
**गिरणी व्यवस्थापन प्रणाली | Responsive Web Application for Mobile & Desktop**

---

## 🌟 Executive Overview
**ChakkiMate (चक्कीमेट)** is an end-to-end business management application tailored specifically for flour mill (*girni*) owners. Built strictly to the **Girni Management System Software Requirements Specification (SRS v1.0)**, it streamlines:
1. **Customer Grain Grinding (ग्राहकांचे धान्य दळण)**: Token generation, weight tracking, grinding charges calculation, status workflow (*Pending &rarr; In Progress &rarr; Completed &rarr; Delivered*), WhatsApp share, and printable slips.
2. **Grain & Finished Flour Sales (धान्य व पीठ विक्री)**: Multi-item sales, automated price calculations, stock deduction, and thermal/A4 invoice generation.
3. **Own-Grain Flour Processing / Production (स्वतःचे पीठ उत्पादन)**: Converting mill-owned raw grain into finished packaged flour with automatic yield percentage and bran/husk wastage tracking.
4. **Separated Inventory Ledger (साठा लेजर)**: Strict segregation of Raw Grain vs Finished Flour stock. Full auditable In/Out movement logs with manual adjustment auditing.
5. **Billing, Payments & Receivables (बिले व देयके)**: PDF invoice download, print-friendly browser views, one-click WhatsApp sharing, and partial/advance payment tracking.
6. **Business Analytics & Reports (अहवाल)**: Daily/monthly sales, grinding revenue, item-wise breakdown, production yield, debtor list, and Income vs. Expense statement.
7. **Bilingual Engine (मराठी व English)**: One-click real-time language switch between Marathi (मराठी) and English across all screens and bills.

---

## ⚙️ Technology Stack
- **Backend**: Python 3.14 + Django 6.1
- **Frontend**: Responsive HTML5, CSS3, Bootstrap 5.3, Bootstrap Icons, Chart.js
- **Database**: Dual Mode — SQLite3 (out-of-the-box local zero-config) & MySQL (utf8mb4 for cloud/production)
- **PDF Engine**: ReportLab with Unicode Marathi support
- **Messaging**: Native WhatsApp Click-to-Chat integration (`https://wa.me/`)

---

## 🚀 Quickstart Guide

### 1. Prerequisites
Ensure Python 3.10+ is installed on your system.

### 2. Activate Virtual Environment
```bash
cd /Users/Sona/.gemini/antigravity/scratch/chakkimate
source venv/bin/activate
```

### 3. Run Migrations & Seed Sample Master Data
```bash
python manage.py migrate
python manage.py seed_data
```

### 4. Start the Server
```bash
python manage.py runserver 0.0.0.0:8000
```
Open your browser at: **`http://localhost:8000/`**

---

## 🔑 Default Login Credentials
- **Username**: `owner`
- **Password**: `owner`
*(Can be changed anytime through the Django admin or profile settings)*

---

## 📐 Core Business Rules Implemented
| Business Rule | Implementation in ChakkiMate |
| :--- | :--- |
| **Precision** | All weights are stored as `Decimal(12, 3)` in KG (e.g. `12.500 KG`). All financial amounts use `Decimal(12, 2)` (e.g. `₹450.00`). |
| **Customer Grain Grinding** | When a customer brings their own grain (`CUSTOMER`), **the mill's stock is untouched**. Only the service charge is billed. |
| **Mill Grain Grinding** | When grain is supplied by the mill (`MILL`), raw grain stock is automatically deducted. |
| **Own Production Batches** | Consuming raw grain decreases raw stock, producing finished flour increases flour stock, and wastage/bran is logged. Yield % = `(Output / Input) * 100`. |
| **Atomic Transactions** | All stock and monetary adjustments run inside `@transaction.atomic` blocks to guarantee zero data inconsistency. |
| **Snapshot Pricing** | Rates applied on transactions are permanently frozen on transaction lines so master rate edits never alter historical bills. |

---

## 🗄️ MySQL Database Setup (Optional for Production)
ChakkiMate automatically connects to MySQL when environment variables are detected:

```bash
export DB_ENGINE=mysql
export MYSQL_DATABASE=chakkimate_db
export MYSQL_USER=your_db_user
export MYSQL_PASSWORD=your_db_password
export MYSQL_HOST=localhost
export MYSQL_PORT=3306

python manage.py migrate
```

---

## 🧪 Automated Test Verification
ChakkiMate comes with an automated test suite verifying all 8 scenarios outlined in Section 11 of the SRS:
```bash
python manage.py test girni
```
Output:
```text
Found 8 test(s).
Creating test database for alias 'default'...
........
----------------------------------------------------------------------
Ran 8 tests in 2.48s

OK
```

---

## 💾 Database Backup & Restore Utility
ChakkiMate includes a backup and restore tool:
```bash
# Create a timestamped backup
./backup_restore.sh backup

# Check status and existing backups
./backup_restore.sh status

# Restore a specific backup file
./backup_restore.sh restore ./backups/sqlite_db_20261109_122349.sqlite3
```

---

## 📱 Mobile Experience
ChakkiMate is built mobile-first. Mill operators can comfortably book grinding orders, print tokens, record cash/UPI payments, and send instant WhatsApp bills directly from their Android or iPhone smartphone.
