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
