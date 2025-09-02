#!/usr/bin/env python3
"""
Personal Finance Tracker - single-file Tkinter + SQLite app (offline)

Save this file as `finance_app.py` and run:
    python finance_app.py

Features (MVP):
- Add transactions (date, type, category, amount, notes, optional goal)
- List & filter transactions
- Create simple savings goals and track progress
- Monthly income/expense summary for the current month
- Export transactions to CSV and backup the DB file

No external libraries required (pure standard library + Tkinter).
"""

from __future__ import annotations
import sqlite3
from decimal import Decimal, InvalidOperation, getcontext
from datetime import date, datetime, timedelta
import os
import shutil
import csv
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

# --- Config ---
DB_FILE = "finance.db"
BACKUP_DIR = "backups"
getcontext().prec = 28  # Decimal precision


# --- Database Helpers ---
def init_db() -> None:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL
        )
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            target_amount TEXT NOT NULL,
            deadline TEXT
        )
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            type TEXT NOT NULL,
            category TEXT NOT NULL,
            amount TEXT NOT NULL,
            notes TEXT,
            goal_id INTEGER
        )
        """
    )
    conn.commit()

    # Seed default categories if empty
    c.execute("SELECT COUNT(1) as cnt FROM categories")
    cnt = c.fetchone()["cnt"]
    if cnt == 0:
        default_cats = [
            "Salary",
            "Food",
            "Rent",
            "Utilities",
            "Transport",
            "Entertainment",
            "Health",
            "Savings",
            "Miscellaneous",
        ]
        c.executemany("INSERT INTO categories (name) VALUES (?)", [(x,) for x in default_cats])
        conn.commit()

    conn.close()


def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def get_categories() -> list[str]:
    conn = get_connection()
    rows = conn.execute("SELECT name FROM categories ORDER BY name").fetchall()
    conn.close()
    return [r["name"] for r in rows]


def get_goals() -> list[dict]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM goals ORDER BY id").fetchall()
    goals = []
    for r in rows:
        gid = r["id"]
        target = Decimal(r["target_amount"])
        row_sum = conn.execute("SELECT amount FROM transactions WHERE goal_id = ?", (gid,)).fetchall()
        total = sum(Decimal(x["amount"]) for x in row_sum) if row_sum else Decimal(0)
        goals.append({"id": gid, "name": r["name"], "target": target, "deadline": r["deadline"], "progress": total})
    conn.close()
    return goals


def add_goal(name: str, target_amount: Decimal, deadline: str | None) -> None:
    conn = get_connection()
    conn.execute("INSERT INTO goals (name, target_amount, deadline) VALUES (?,?,?)", (name, str(target_amount), deadline))
    conn.commit()
    conn.close()


def add_transaction(date_str: str, ttype: str, category: str, amount: Decimal, notes: str, goal_id: int | None) -> None:
    conn = get_connection()
    conn.execute(
        "INSERT INTO transactions (date,type,category,amount,notes,goal_id) VALUES (?,?,?,?,?,?)",
        (date_str, ttype, category, str(amount), notes, goal_id),
    )
    conn.commit()
    conn.close()


def delete_transaction(tx_id: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM transactions WHERE id=?", (tx_id,))
    conn.commit()
    conn.close()


def fetch_transactions(date_from: str | None = None, date_to: str | None = None, category: str | None = None, search: str | None = None, limit: int = 2000):
    conn = get_connection()
    q = "SELECT t.*, g.name as goal_name FROM transactions t LEFT JOIN goals g ON t.goal_id = g.id WHERE 1=1"
    params = []
    if date_from:
        q += " AND date >= ?"; params.append(date_from)
    if date_to:
        q += " AND date <= ?"; params.append(date_to)
    if category and category != "All":
        q += " AND category = ?"; params.append(category)
    if search:
        q += " AND (notes LIKE ? OR category LIKE ?)"; params.extend([f"%{search}%", f"%{search}%"])
    q += " ORDER BY date DESC, id DESC LIMIT ?"; params.append(limit)
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return rows


def sum_month(month_year: str | None = None) -> tuple[Decimal, Decimal]:
    if not month_year:
        month_year = date.today().strftime("%Y-%m")
    y, m = map(int, month_year.split("-"))
    start = date(y, m, 1)
    if m == 12:
        next_month = date(y + 1, 1, 1)
    else:
        next_month = date(y, m + 1, 1)
    end = next_month - timedelta(days=1)
    conn = get_connection()
    rows = conn.execute("SELECT type, amount FROM transactions WHERE date BETWEEN ? AND ?", (start.isoformat(), end.isoformat())).fetchall()
    income = Decimal(0); expense = Decimal(0)
    for r in rows:
        amt = Decimal(r["amount"])
        if r["type"] == "Income":
            income += amt
        else:
            expense += amt
    conn.close()
    return income, expense


# --- Utility helpers ---
def ensure_backup_dir():
    os.makedirs(BACKUP_DIR, exist_ok=True)


def backup_db():
    ensure_backup_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(BACKUP_DIR, f"finance_backup_{ts}.db")
    shutil.copy(DB_FILE, dest)
    return dest


def export_transactions_csv(rows, filename=None):
    if not filename:
        filename = f"transactions_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    with open(filename, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "date", "type", "category", "amount", "notes", "goal_name"])
        for r in rows:
            w.writerow([r["id"], r["date"], r["type"], r["category"], r["amount"], r["notes"], r["goal_name"]])
    return filename


# --- GUI ---
class FinanceApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Personal Finance Tracker (Offline)")
        self.root.geometry("1000x600")

        # top-level frames
        self.left_frame = ttk.Frame(root, padding=(10,10))
        self.left_frame.pack(side=tk.LEFT, fill=tk.Y)

        self.right_frame = ttk.Frame(root, padding=(10,10))
        self.right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self._build_left()
        self._build_right()

        # initialize data
        init_db()
        self.refresh_categories()
        self.refresh_goals()
        self.refresh_transactions()
        self.update_month_summary()

    # Left: Add Transaction + Goals
    def _build_left(self):
        # Add Transaction Card
        card = ttk.LabelFrame(self.left_frame, text="Add Transaction", padding=(10,10))
        card.pack(fill=tk.X, pady=(0,10))

        # Date
        ttk.Label(card, text="Date (YYYY-MM-DD)").grid(row=0, column=0, sticky=tk.W)
        self.date_var = tk.StringVar(value=date.today().isoformat())
        ttk.Entry(card, textvariable=self.date_var).grid(row=0, column=1, sticky=tk.EW, padx=5, pady=2)

        # Type
        ttk.Label(card, text="Type").grid(row=1, column=0, sticky=tk.W)
        self.type_var = tk.StringVar(value="Expense")
        ttk.Combobox(card, textvariable=self.type_var, values=["Expense","Income"], state="readonly").grid(row=1, column=1, sticky=tk.EW, padx=5, pady=2)

        # Category
        ttk.Label(card, text="Category").grid(row=2, column=0, sticky=tk.W)
        self.cat_var = tk.StringVar()
        self.cat_cb = ttk.Combobox(card, textvariable=self.cat_var, values=[], state="readonly")
        self.cat_cb.grid(row=2, column=1, sticky=tk.EW, padx=5, pady=2)

        # Amount
        ttk.Label(card, text="Amount").grid(row=3, column=0, sticky=tk.W)
        self.amt_var = tk.StringVar()
        ttk.Entry(card, textvariable=self.amt_var).grid(row=3, column=1, sticky=tk.EW, padx=5, pady=2)

        # Goal (optional)
        ttk.Label(card, text="Apply to Goal (optional)").grid(row=4, column=0, sticky=tk.W)
        self.goal_var = tk.StringVar()
        self.goal_cb = ttk.Combobox(card, textvariable=self.goal_var, values=[], state="readonly")
        self.goal_cb.grid(row=4, column=1, sticky=tk.EW, padx=5, pady=2)

        # Notes
        ttk.Label(card, text="Notes").grid(row=5, column=0, sticky=tk.W)
        self.notes_var = tk.StringVar()
        ttk.Entry(card, textvariable=self.notes_var).grid(row=5, column=1, sticky=tk.EW, padx=5, pady=2)

        # Buttons
        add_btn = ttk.Button(card, text="Add Transaction", command=self.on_add_transaction)
        add_btn.grid(row=6, column=0, columnspan=2, sticky=tk.EW, pady=(8,0))

        for i in range(2):
            card.columnconfigure(i, weight=1)

        # Goals Card
        goals_card = ttk.LabelFrame(self.left_frame, text="Goals", padding=(10,10))
        goals_card.pack(fill=tk.X, pady=(0,10))
        self.goals_box = tk.Listbox(goals_card, height=6)
        self.goals_box.pack(fill=tk.X, padx=5, pady=5)
        goals_btn_frame = ttk.Frame(goals_card)
        goals_btn_frame.pack(fill=tk.X, padx=5, pady=(0,5))
        ttk.Button(goals_btn_frame, text="Add Goal", command=self.on_add_goal).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0,5))
        ttk.Button(goals_btn_frame, text="Refresh Goals", command=self.refresh_goals).pack(side=tk.LEFT, expand=True, fill=tk.X)

    # Right: Transactions list, filters, summary
    def _build_right(self):
        # Filter bar
        filter_frame = ttk.Frame(self.right_frame)
        filter_frame.pack(fill=tk.X, pady=(0,10))

        ttk.Label(filter_frame, text="From").pack(side=tk.LEFT)
        self.filter_from = tk.StringVar(value=(date.today().replace(day=1).isoformat()))
        ttk.Entry(filter_frame, width=12, textvariable=self.filter_from).pack(side=tk.LEFT, padx=5)

        ttk.Label(filter_frame, text="To").pack(side=tk.LEFT)
        self.filter_to = tk.StringVar(value=date.today().isoformat())
        ttk.Entry(filter_frame, width=12, textvariable=self.filter_to).pack(side=tk.LEFT, padx=5)

        ttk.Label(filter_frame, text="Category").pack(side=tk.LEFT, padx=(10,0))
        self.filter_cat = tk.StringVar(value="All")
        self.filter_cat_cb = ttk.Combobox(filter_frame, textvariable=self.filter_cat, values=["All"], state="readonly", width=20)
        self.filter_cat_cb.pack(side=tk.LEFT, padx=5)

        ttk.Label(filter_frame, text="Search").pack(side=tk.LEFT, padx=(10,0))
        self.search_var = tk.StringVar()
        ttk.Entry(filter_frame, width=20, textvariable=self.search_var).pack(side=tk.LEFT, padx=5)

        ttk.Button(filter_frame, text="Apply", command=self.refresh_transactions).pack(side=tk.LEFT, padx=5)
        ttk.Button(filter_frame, text="Export CSV", command=self.on_export_csv).pack(side=tk.LEFT, padx=5)
        ttk.Button(filter_frame, text="Backup DB", command=self.on_backup_db).pack(side=tk.LEFT, padx=5)

        # Treeview (transactions)
        cols = ("date", "type", "category", "amount", "goal", "notes")
        self.tree = ttk.Treeview(self.right_frame, columns=cols, show="headings", selectmode="browse")
        for c in cols:
            self.tree.heading(c, text=c.title())
            if c == "notes":
                self.tree.column(c, width=240)
            elif c == "amount":
                self.tree.column(c, width=100, anchor=tk.E)
            else:
                self.tree.column(c, width=100)
        self.tree.pack(fill=tk.BOTH, expand=True)

        # treeview scrollbar
        vsb = ttk.Scrollbar(self.tree, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # bottom controls
        btn_frame = ttk.Frame(self.right_frame)
        btn_frame.pack(fill=tk.X, pady=(8,0))
        ttk.Button(btn_frame, text="Delete Selected", command=self.on_delete_selected).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="Refresh", command=self.refresh_transactions).pack(side=tk.LEFT, padx=5)

        # Summary card
        summary_card = ttk.LabelFrame(self.right_frame, text="This Month Summary", padding=(10,10))
        summary_card.pack(fill=tk.X, pady=(8,0))
        self.income_var = tk.StringVar(value="0.00")
        self.expense_var = tk.StringVar(value="0.00")
        self.balance_var = tk.StringVar(value="0.00")
        ttk.Label(summary_card, text="Income:").grid(row=0, column=0, sticky=tk.W)
        ttk.Label(summary_card, textvariable=self.income_var).grid(row=0, column=1, sticky=tk.E)
        ttk.Label(summary_card, text="Expense:").grid(row=1, column=0, sticky=tk.W)
        ttk.Label(summary_card, textvariable=self.expense_var).grid(row=1, column=1, sticky=tk.E)
        ttk.Label(summary_card, text="Balance (Income - Expense):").grid(row=2, column=0, sticky=tk.W)
        ttk.Label(summary_card, textvariable=self.balance_var).grid(row=2, column=1, sticky=tk.E)

        for i in range(2):
            summary_card.columnconfigure(i, weight=1)

    # --- Event handlers / actions ---
    def refresh_categories(self):
        cats = get_categories()
        vals = cats.copy()
        self.cat_cb.config(values=vals)
        # filter combobox
        self.filter_cat_cb.config(values=["All"] + vals)
        # if current selection not in list, set to first cat
        if not self.cat_var.get() and vals:
            self.cat_var.set(vals[0])

    def refresh_goals(self):
        goals = get_goals()
        names = [g["name"] for g in goals]
        self.goal_cb.config(values=[""] + names)
        # populate left goals listbox
        self.goals_box.delete(0, tk.END)
        for g in goals:
            prog = f"{g['progress']:.2f}/{g['target']:.2f}"
            dl = g["deadline"] if g["deadline"] else "-"
            self.goals_box.insert(tk.END, f"{g['name']}  ({prog})  deadline: {dl}")

    def refresh_transactions(self):
        from_date = self.filter_from.get().strip() or None
        to_date = self.filter_to.get().strip() or None
        cat = self.filter_cat.get() or None
        search = self.search_var.get().strip() or None
        try:
            rows = fetch_transactions(date_from=from_date, date_to=to_date, category=cat, search=search, limit=2000)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to fetch transactions: {e}")
            return
        # clear tree
        for r in self.tree.get_children():
            self.tree.delete(r)
        # insert rows
        for row in rows:
            goal_name = row["goal_name"] if row["goal_name"] else ""
            self.tree.insert("", tk.END, iid=row["id"], values=(row["date"], row["type"], row["category"], f"{Decimal(row['amount']):.2f}", goal_name, row["notes"] or ""))
        self.update_month_summary()

    def on_add_transaction(self):
        d = self.date_var.get().strip()
        t = self.type_var.get().strip()
        cat = self.cat_var.get().strip()
        amt = self.amt_var.get().strip()
        notes = self.notes_var.get().strip()
        goal_name = self.goal_var.get().strip()

        # validation
        try:
            # date validation
            datetime.fromisoformat(d)
        except Exception:
            messagebox.showerror("Validation", "Date must be in YYYY-MM-DD format.")
            return
        try:
            dec = Decimal(amt)
            if dec <= 0:
                raise InvalidOperation
        except Exception:
            messagebox.showerror("Validation", "Amount must be a positive number (e.g. 12.50).")
            return
        # goal lookup
        goal_id = None
        if goal_name:
            conn = get_connection()
            r = conn.execute("SELECT id FROM goals WHERE name = ?", (goal_name,)).fetchone()
            conn.close()
            if r:
                goal_id = r["id"]

        try:
            add_transaction(d, t, cat, dec, notes, goal_id)
            messagebox.showinfo("Saved", "Transaction saved.")
            # clear inputs except date
            self.amt_var.set("")
            self.notes_var.set("")
            self.goal_var.set("")
            self.refresh_transactions()
            self.refresh_goals()
        except Exception as e:
            messagebox.showerror("Error", f"Could not save transaction: {e}")

    def on_delete_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Delete", "Select a transaction to delete.")
            return
        tx_id = int(sel[0])
        if not messagebox.askyesno("Confirm", "Delete the selected transaction?"):
            return
        try:
            delete_transaction(tx_id)
            self.refresh_transactions()
            self.refresh_goals()
        except Exception as e:
            messagebox.showerror("Error", f"Could not delete: {e}")

    def on_add_goal(self):
        dialog = AddGoalDialog(self.root)
        self.root.wait_window(dialog.top)
        if dialog.result:
            name, target, deadline = dialog.result
            try:
                add_goal(name, target, deadline)
                messagebox.showinfo("OK", "Goal added.")
                self.refresh_goals()
            except Exception as e:
                messagebox.showerror("Error", f"Could not add goal: {e}")

    def on_export_csv(self):
        rows = fetch_transactions(date_from=self.filter_from.get().strip() or None, date_to=self.filter_to.get().strip() or None, category=self.filter_cat.get() or None, search=self.search_var.get().strip() or None, limit=10000)
        if not rows:
            messagebox.showinfo("Export", "No transactions to export for the current filter.")
            return
        fname = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files","*.csv")], initialfile=f"transactions_{datetime.now().strftime('%Y%m%d')}.csv")
        if not fname:
            return
        try:
            export_transactions_csv(rows, fname)
            messagebox.showinfo("Exported", f"Transactions exported to:\n{fname}")
        except Exception as e:
            messagebox.showerror("Error", f"Export failed: {e}")

    def on_backup_db(self):
        try:
            dest = backup_db()
            messagebox.showinfo("Backup", f"Database backed up to:\n{dest}")
        except Exception as e:
            messagebox.showerror("Error", f"Backup failed: {e}")

    def update_month_summary(self):
        my = date.today().strftime("%Y-%m")
        income, expense = sum_month(my)
        bal = income - expense
        self.income_var.set(f"{income:.2f}")
        self.expense_var.set(f"{expense:.2f}")
        self.balance_var.set(f"{bal:.2f}")


class AddGoalDialog:
    def __init__(self, parent):
        self.top = tk.Toplevel(parent)
        self.top.title("Add Goal")
        self.top.grab_set()
        ttk.Label(self.top, text="Name").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.name_var = tk.StringVar()
        ttk.Entry(self.top, textvariable=self.name_var).grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(self.top, text="Target Amount").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.target_var = tk.StringVar()
        ttk.Entry(self.top, textvariable=self.target_var).grid(row=1, column=1, padx=5, pady=5)

        ttk.Label(self.top, text="Deadline (YYYY-MM-DD, optional)").grid(row=2, column=0, sticky=tk.W, padx=5, pady=5)
        self.deadline_var = tk.StringVar()
        ttk.Entry(self.top, textvariable=self.deadline_var).grid(row=2, column=1, padx=5, pady=5)

        btn_frame = ttk.Frame(self.top)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=10)
        ttk.Button(btn_frame, text="Add", command=self.on_add).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=self.on_cancel).pack(side=tk.LEFT, padx=5)

        for i in range(2):
            self.top.columnconfigure(i, weight=1)

        self.result = None

    def on_add(self):
        name = self.name_var.get().strip()
        target = self.target_var.get().strip()
        deadline = self.deadline_var.get().strip() or None
        if not name or not target:
            messagebox.showerror("Validation", "Name and target amount are required.")
            return
        try:
            dec = Decimal(target)
            if dec <= 0:
                raise InvalidOperation
        except Exception:
            messagebox.showerror("Validation", "Target amount must be a positive number.")
            return
        if deadline:
            try:
                datetime.fromisoformat(deadline)
            except Exception:
                messagebox.showerror("Validation", "Deadline must be YYYY-MM-DD or left empty.")
                return
        self.result = (name, dec, deadline)
        self.top.destroy()

    def on_cancel(self):
        self.top.destroy()


def main():
    init_db()
    root = tk.Tk()
    app = FinanceApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()