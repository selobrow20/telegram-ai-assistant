import sqlite3
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional
from config import DATABASE_PATH

def get_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('income', 'expense')),
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                description TEXT,
                date TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'completed')),
                due_date TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notification_settings (
                user_id INTEGER PRIMARY KEY,
                user_name TEXT,
                chat_id INTEGER,
                daily_recap_enabled INTEGER DEFAULT 1,
                daily_recap_time TEXT DEFAULT '07:00',
                weekly_recap_enabled INTEGER DEFAULT 1,
                monthly_report_enabled INTEGER DEFAULT 1,
                scheduled_reports_enabled INTEGER DEFAULT 1,
                scheduled_day INTEGER DEFAULT 25,
                last_daily_sent TEXT,
                last_weekly_sent TEXT,
                last_monthly_sent TEXT,
                last_scheduled_sent TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()


# --- Modul Keuangan ---

def add_transaction(user_id: int, type_: str, amount: float, category: str, description: str = "", trans_date: Optional[str] = None) -> int:
    if not trans_date:
        trans_date = date.today().isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO transactions (user_id, type, amount, category, description, date)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, type_.lower(), float(amount), category.strip().title(), description.strip(), trans_date))
        conn.commit()
        return cursor.lastrowid

def add_multiple_transactions(user_id: int, transactions: List[Dict[str, Any]]) -> int:
    today_str = date.today().isoformat()
    inserted = 0
    with get_connection() as conn:
        cursor = conn.cursor()
        for t in transactions:
            t_type = "income" if "masuk" in str(t.get("type", "")).lower() or "income" in str(t.get("type", "")).lower() else "expense"
            amt = float(t.get("amount", 0))
            if amt <= 0:
                continue
            cat = str(t.get("category", "Lain-lain")).strip().title()
            desc = str(t.get("description", "")).strip()
            dt = str(t.get("date") or today_str)
            cursor.execute('''
                INSERT INTO transactions (user_id, type, amount, category, description, date)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, t_type, amt, cat, desc, dt))
            inserted += 1
        conn.commit()
    return inserted

def get_balance(user_id: int) -> Dict[str, float]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT 
                COALESCE(SUM(CASE WHEN type = 'income' THEN amount ELSE 0 END), 0) as total_income,
                COALESCE(SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END), 0) as total_expense
            FROM transactions
            WHERE user_id = ?
        ''', (user_id,))
        row = cursor.fetchone()
        income = float(row['total_income'])
        expense = float(row['total_expense'])
        return {
            'total_income': income,
            'total_expense': expense,
            'balance': income - expense
        }

def get_transactions_by_period(user_id: int, period: str = "month") -> List[Dict[str, Any]]:
    today = date.today()
    if period == "today":
        start_date = today.isoformat()
    elif period == "week":
        start_date = (today - timedelta(days=7)).isoformat()
    elif period == "month":
        start_date = today.replace(day=1).isoformat()
    else:
        start_date = "1970-01-01"

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, type, amount, category, description, date, created_at
            FROM transactions
            WHERE user_id = ? AND date >= ?
            ORDER BY date DESC, id DESC
        ''', (user_id, start_date))
        return [dict(row) for row in cursor.fetchall()]

def get_category_breakdown(user_id: int, period: str = "month") -> Dict[str, Any]:
    today = date.today()
    if period == "today":
        start_date = today.isoformat()
    elif period == "week":
        start_date = (today - timedelta(days=7)).isoformat()
    elif period == "month":
        start_date = today.replace(day=1).isoformat()
    else:
        start_date = "1970-01-01"

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT type, category, SUM(amount) as total, COUNT(id) as count
            FROM transactions
            WHERE user_id = ? AND date >= ?
            GROUP BY type, category
            ORDER BY total DESC
        ''', (user_id, start_date))
        rows = cursor.fetchall()
        
        income_cat = []
        expense_cat = []
        tot_inc = 0.0
        tot_exp = 0.0

        for r in rows:
            item = {'category': r['category'], 'total': float(r['total']), 'count': r['count']}
            if r['type'] == 'income':
                income_cat.append(item)
                tot_inc += item['total']
            else:
                expense_cat.append(item)
                tot_exp += item['total']

        return {
            'period': period,
            'start_date': start_date,
            'total_income': tot_inc,
            'total_expense': tot_exp,
            'balance': tot_inc - tot_exp,
            'income_categories': income_cat,
            'expense_categories': expense_cat
        }

def delete_transaction(user_id: int, trans_id: int) -> bool:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM transactions WHERE id = ? AND user_id = ?', (trans_id, user_id))
        conn.commit()
        return cursor.rowcount > 0

def reset_user_finances(user_id: int) -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM transactions WHERE user_id = ?', (user_id,))
        conn.commit()
        return cursor.rowcount

# --- Modul Catatan & To-Do Harian ---

def add_task(user_id: int, title: str, due_date: Optional[str] = None) -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO tasks (user_id, title, due_date)
            VALUES (?, ?, ?)
        ''', (user_id, title.strip(), due_date))
        conn.commit()
        return cursor.lastrowid

def get_tasks(user_id: int, status: Optional[str] = 'pending') -> List[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        if status:
            cursor.execute('''
                SELECT id, title, status, due_date, created_at
                FROM tasks
                WHERE user_id = ? AND status = ?
                ORDER BY id DESC
            ''', (user_id, status))
        else:
            cursor.execute('''
                SELECT id, title, status, due_date, created_at
                FROM tasks
                WHERE user_id = ?
                ORDER BY id DESC
            ''', (user_id,))
        return [dict(row) for row in cursor.fetchall()]

def update_task_status(user_id: int, task_id: int, status: str) -> bool:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE tasks SET status = ? WHERE id = ? AND user_id = ?
        ''', (status, task_id, user_id))
        conn.commit()
        return cursor.rowcount > 0

def delete_task(user_id: int, task_id: int) -> bool:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM tasks WHERE id = ? AND user_id = ?', (task_id, user_id))
        conn.commit()
        return cursor.rowcount > 0

def add_note(user_id: int, content: str, title: str = "") -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO notes (user_id, title, content)
            VALUES (?, ?, ?)
        ''', (user_id, title.strip(), content.strip()))
        conn.commit()
        return cursor.lastrowid

def get_notes(user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, title, content, created_at
            FROM notes
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
        ''', (user_id, limit))
        return [dict(row) for row in cursor.fetchall()]

def delete_note(user_id: int, note_id: int) -> bool:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM notes WHERE id = ? AND user_id = ?', (note_id, user_id))
        conn.commit()
        return cursor.rowcount > 0

# --- Modul Notifikasi Cerdas ---

def register_or_update_user(user_id: int, user_name: str, chat_id: Optional[int] = None):
    c_id = chat_id or user_id
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO notification_settings (user_id, user_name, chat_id)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                user_name = excluded.user_name,
                chat_id = excluded.chat_id,
                updated_at = CURRENT_TIMESTAMP
        ''', (user_id, user_name, c_id))
        conn.commit()

def get_notification_settings(user_id: int) -> Dict[str, Any]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM notification_settings WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        if row:
            return dict(row)
        return {
            'user_id': user_id,
            'user_name': 'Teman',
            'chat_id': user_id,
            'daily_recap_enabled': 1,
            'daily_recap_time': '07:00',
            'weekly_recap_enabled': 1,
            'monthly_report_enabled': 1,
            'scheduled_reports_enabled': 1,
            'scheduled_day': 25,
            'last_daily_sent': None,
            'last_weekly_sent': None,
            'last_monthly_sent': None,
            'last_scheduled_sent': None
        }

def update_notification_setting(user_id: int, field: str, value: Any) -> bool:
    allowed_fields = {
        'daily_recap_enabled', 'daily_recap_time',
        'weekly_recap_enabled', 'monthly_report_enabled',
        'scheduled_reports_enabled', 'scheduled_day',
        'last_daily_sent', 'last_weekly_sent',
        'last_monthly_sent', 'last_scheduled_sent'
    }
    if field not in allowed_fields:
        return False
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f'''
            UPDATE notification_settings
            SET {field} = ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
        ''', (value, user_id))
        conn.commit()
        return cursor.rowcount > 0

def get_all_active_users_for_notification() -> List[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM notification_settings')
        return [dict(row) for row in cursor.fetchall()]

def get_yesterday_expenses(user_id: int) -> Dict[str, Any]:
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT category, description, amount
            FROM transactions
            WHERE user_id = ? AND type = 'expense' AND date = ?
            ORDER BY amount DESC
        ''', (user_id, yesterday))
        rows = [dict(r) for r in cursor.fetchall()]
        
        total = sum(r['amount'] for r in rows)
        cat_summary = {}
        for r in rows:
            cat = r['category']
            cat_summary[cat] = cat_summary.get(cat, 0.0) + r['amount']
            
        return {
            'date': yesterday,
            'total_expense': total,
            'count': len(rows),
            'items': rows,
            'categories': [{'category': k, 'total': v} for k, v in sorted(cat_summary.items(), key=lambda x: x[1], reverse=True)]
        }

def get_last_7_days_expenses(user_id: int) -> Dict[str, Any]:
    today = date.today()
    start_date = (today - timedelta(days=7)).isoformat()
    end_date = (today - timedelta(days=1)).isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT type, category, SUM(amount) as total, COUNT(id) as count
            FROM transactions
            WHERE user_id = ? AND date BETWEEN ? AND ?
            GROUP BY type, category
            ORDER BY total DESC
        ''', (user_id, start_date, end_date))
        rows = cursor.fetchall()
        tot_inc = 0.0
        tot_exp = 0.0
        exp_cats = []
        for r in rows:
            if r['type'] == 'income':
                tot_inc += float(r['total'])
            else:
                tot_exp += float(r['total'])
                exp_cats.append({'category': r['category'], 'total': float(r['total']), 'count': r['count']})
        return {
            'start_date': start_date,
            'end_date': end_date,
            'total_income': tot_inc,
            'total_expense': tot_exp,
            'balance': tot_inc - tot_exp,
            'top_expense_categories': exp_cats
        }

def get_previous_month_summary(user_id: int) -> Dict[str, Any]:
    today = date.today()
    first_this_month = today.replace(day=1)
    last_prev_month = first_this_month - timedelta(days=1)
    first_prev_month = last_prev_month.replace(day=1)
    
    start_date = first_prev_month.isoformat()
    end_date = last_prev_month.isoformat()
    
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT type, category, SUM(amount) as total, COUNT(id) as count
            FROM transactions
            WHERE user_id = ? AND date BETWEEN ? AND ?
            GROUP BY type, category
            ORDER BY total DESC
        ''', (user_id, start_date, end_date))
        rows = cursor.fetchall()
        tot_inc = 0.0
        tot_exp = 0.0
        exp_cats = []
        inc_cats = []
        for r in rows:
            if r['type'] == 'income':
                tot_inc += float(r['total'])
                inc_cats.append({'category': r['category'], 'total': float(r['total']), 'count': r['count']})
            else:
                tot_exp += float(r['total'])
                exp_cats.append({'category': r['category'], 'total': float(r['total']), 'count': r['count']})
        return {
            'month_name': first_prev_month.strftime('%B %Y'),
            'start_date': start_date,
            'end_date': end_date,
            'total_income': tot_inc,
            'total_expense': tot_exp,
            'balance': tot_inc - tot_exp,
            'expense_categories': exp_cats,
            'income_categories': inc_cats
        }

