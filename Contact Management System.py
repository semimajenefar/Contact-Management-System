import hashlib
import sqlite3
import tkinter as tk
from datetime import date, datetime
from tkinter import messagebox, ttk

DB_NAME = "contacts.db"
DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "admin123"
DEFAULT_SECURITY_ANSWER = "mkce"
THEME = {
    "bg": "#f4f7fb",
    "surface": "#ffffff",
    "surface_soft": "#eef4ff",
    "primary": "#0f4c81",
    "primary_dark": "#0a3358",
    "accent": "#29a19c",
    "text": "#102a43",
    "muted": "#486581",
    "danger": "#d64545",
}


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class ContactDatabase:
    def __init__(self, db_path: str) -> None:
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        self._create_tables()
        self._migrate_legacy_contacts()
        self._ensure_default_user()

    def _create_tables(self) -> None:
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                security_answer_hash TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS contacts_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                first_name TEXT NOT NULL,
                last_name TEXT,
                phone TEXT NOT NULL,
                email TEXT,
                birthday TEXT,
                notes TEXT,
                emergency INTEGER DEFAULT 0,
                birthday_reminder INTEGER DEFAULT 1,
                linkedin_id TEXT,
                github_id TEXT,
                address TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self._ensure_contacts_columns()
        self.conn.commit()

    def _ensure_contacts_columns(self) -> None:
        self.cursor.execute("PRAGMA table_info(contacts_v2)")
        existing_columns = {row["name"] for row in self.cursor.fetchall()}
        expected_columns = {
            "notes": "ALTER TABLE contacts_v2 ADD COLUMN notes TEXT",
            "emergency": "ALTER TABLE contacts_v2 ADD COLUMN emergency INTEGER DEFAULT 0",
            "birthday_reminder": "ALTER TABLE contacts_v2 ADD COLUMN birthday_reminder INTEGER DEFAULT 1",
            "linkedin_id": "ALTER TABLE contacts_v2 ADD COLUMN linkedin_id TEXT",
            "github_id": "ALTER TABLE contacts_v2 ADD COLUMN github_id TEXT",
            "address": "ALTER TABLE contacts_v2 ADD COLUMN address TEXT",
        }
        for column_name, alter_sql in expected_columns.items():
            if column_name not in existing_columns:
                self.cursor.execute(alter_sql)

    def _table_exists(self, table_name: str) -> bool:
        self.cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name = ?", (table_name,)
        )
        return self.cursor.fetchone() is not None

    def _migrate_legacy_contacts(self) -> None:
        if not self._table_exists("contacts"):
            return

        self.cursor.execute("SELECT COUNT(*) AS total FROM contacts_v2")
        if self.cursor.fetchone()["total"] > 0:
            return

        self.cursor.execute("PRAGMA table_info(contacts)")
        legacy_columns = {row["name"] for row in self.cursor.fetchall()}
        if not legacy_columns:
            return

        select_parts = []
        if {"first_name", "last_name"} <= legacy_columns:
            select_parts.extend(["first_name", "last_name"])
        elif "name" in legacy_columns:
            select_parts.extend(["name AS first_name", "'' AS last_name"])
        else:
            return

        select_parts.append("phone" if "phone" in legacy_columns else "'' AS phone")
        select_parts.append("email" if "email" in legacy_columns else "'' AS email")
        select_parts.append("birthday" if "birthday" in legacy_columns else "'' AS birthday")
        select_parts.append("notes" if "notes" in legacy_columns else "'' AS notes")
        select_parts.append("emergency" if "emergency" in legacy_columns else "0 AS emergency")
        select_parts.append(
            "birthday_reminder" if "birthday_reminder" in legacy_columns else "1 AS birthday_reminder"
        )
        select_parts.append("linkedin_id" if "linkedin_id" in legacy_columns else "'' AS linkedin_id")
        select_parts.append("github_id" if "github_id" in legacy_columns else "'' AS github_id")
        select_parts.append("address" if "address" in legacy_columns else "'' AS address")

        # Map alternate legacy column names from older app versions.
        if "linkedin_id" not in legacy_columns and "linkedin" in legacy_columns:
            select_parts[-3] = "linkedin AS linkedin_id"
        if "github_id" not in legacy_columns and "github" in legacy_columns:
            select_parts[-2] = "github AS github_id"

        query = f"SELECT {', '.join(select_parts)} FROM contacts"
        self.cursor.execute(query)
        rows = self.cursor.fetchall()
        if not rows:
            return

        migrated_rows = []
        for row in rows:
            first_name = (row["first_name"] or "").strip()
            last_name = (row["last_name"] or "").strip()

            # If old data stored full name in first_name, split once for better display.
            if first_name and not last_name and " " in first_name:
                parts = first_name.split(" ", 1)
                first_name = parts[0].strip()
                last_name = parts[1].strip()

            migrated_rows.append(
                (
                    first_name or "Unknown",
                    last_name,
                    row["phone"] or "",
                    row["email"] or "",
                    row["birthday"] or "",
                    row["notes"] or "",
                    self._to_int_flag(row["emergency"], default=0),
                    self._to_int_flag(row["birthday_reminder"], default=1),
                    row["linkedin_id"] or "",
                    row["github_id"] or "",
                    row["address"] or "",
                )
            )

        self.cursor.executemany(
            """
            INSERT INTO contacts_v2
            (first_name, last_name, phone, email, birthday, notes, emergency, birthday_reminder, linkedin_id, github_id, address)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            migrated_rows,
        )
        self.conn.commit()

    @staticmethod
    def _to_int_flag(value, default: int = 0) -> int:
        if value is None:
            return default
        if isinstance(value, bool):
            return 1 if value else 0
        if isinstance(value, (int, float)):
            return 1 if int(value) != 0 else 0

        cleaned = str(value).strip().lower()
        if cleaned in {"1", "yes", "y", "true", "t", "on"}:
            return 1
        if cleaned in {"0", "no", "n", "false", "f", "off", ""}:
            return 0
        return default

    def _ensure_default_user(self) -> None:
        self.cursor.execute("SELECT id FROM users WHERE username = ?", (DEFAULT_USERNAME,))
        if self.cursor.fetchone() is None:
            self.cursor.execute(
                """
                INSERT INTO users (username, password_hash, security_answer_hash)
                VALUES (?, ?, ?)
                """,
                (
                    DEFAULT_USERNAME,
                    hash_text(DEFAULT_PASSWORD),
                    hash_text(DEFAULT_SECURITY_ANSWER),
                ),
            )
            self.conn.commit()

    def validate_login(self, username: str, password: str) -> bool:
        self.cursor.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
        row = self.cursor.fetchone()
        if row is None:
            return False
        return row["password_hash"] == hash_text(password)

    def reset_password(self, username: str, security_answer: str, new_password: str) -> bool:
        self.cursor.execute(
            "SELECT id, security_answer_hash FROM users WHERE username = ?", (username,)
        )
        row = self.cursor.fetchone()
        if row is None:
            return False
        if row["security_answer_hash"] != hash_text(security_answer):
            return False
        self.cursor.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_text(new_password), row["id"]),
        )
        self.conn.commit()
        return True

    def add_contact(self, data: dict) -> None:
        self.cursor.execute(
            """
            INSERT INTO contacts_v2
            (first_name, last_name, phone, email, birthday, notes, emergency, birthday_reminder, linkedin_id, github_id, address)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["first_name"],
                data["last_name"],
                data["phone"],
                data["email"],
                data["birthday"],
                data["notes"],
                data["emergency"],
                data["birthday_reminder"],
                data["linkedin_id"],
                data["github_id"],
                data["address"],
            ),
        )
        self.conn.commit()

    def update_contact(self, contact_id: int, data: dict) -> None:
        self.cursor.execute(
            """
            UPDATE contacts_v2
            SET first_name = ?, last_name = ?, phone = ?, email = ?, birthday = ?, notes = ?,
                emergency = ?, birthday_reminder = ?, linkedin_id = ?, github_id = ?, address = ?
            WHERE id = ?
            """,
            (
                data["first_name"],
                data["last_name"],
                data["phone"],
                data["email"],
                data["birthday"],
                data["notes"],
                data["emergency"],
                data["birthday_reminder"],
                data["linkedin_id"],
                data["github_id"],
                data["address"],
                contact_id,
            ),
        )
        self.conn.commit()

    def delete_contact(self, contact_id: int) -> None:
        self.cursor.execute("DELETE FROM contacts_v2 WHERE id = ?", (contact_id,))
        self.conn.commit()

    def get_contact(self, contact_id: int):
        self.cursor.execute("SELECT * FROM contacts_v2 WHERE id = ?", (contact_id,))
        return self.cursor.fetchone()

    def get_contacts(self, keyword: str = "", emergency_only: bool = False):
        base_query = """
            SELECT id, first_name, last_name, phone, email, birthday, emergency, linkedin_id, github_id, address
            FROM contacts_v2
        """
        conditions = []
        params = []

        if emergency_only:
            conditions.append("emergency = 1")

        if keyword:
            search_term = f"%{keyword}%"
            conditions.append(
                """
                (
                    first_name LIKE ? OR
                    last_name LIKE ? OR
                    phone LIKE ? OR
                    email LIKE ? OR
                    linkedin_id LIKE ? OR
                    github_id LIKE ? OR
                    address LIKE ?
                )
                """
            )
            params.extend(
                [
                    search_term,
                    search_term,
                    search_term,
                    search_term,
                    search_term,
                    search_term,
                    search_term,
                ]
            )

        if conditions:
            base_query += " WHERE " + " AND ".join(conditions)

        base_query += " ORDER BY first_name, last_name"
        self.cursor.execute(base_query, params)
        return self.cursor.fetchall()

    def get_upcoming_birthdays(self, days_ahead: int = 30):
        today = date.today()
        reminders = []

        self.cursor.execute(
            """
            SELECT first_name, last_name, birthday, phone
            FROM contacts_v2
            WHERE birthday IS NOT NULL AND birthday != '' AND birthday_reminder = 1
            """
        )

        for row in self.cursor.fetchall():
            try:
                parsed_bday = datetime.strptime(row["birthday"], "%d-%m-%Y")
                month = parsed_bday.month
                day = parsed_bday.day
            except ValueError:
                continue

            try:
                next_birthday = date(today.year, month, day)
            except ValueError:
                # Handles rare invalid cases such as 29-Feb on non-leap years.
                continue

            if next_birthday < today:
                next_birthday = date(today.year + 1, month, day)

            days_left = (next_birthday - today).days
            if 0 <= days_left <= days_ahead:
                full_name = f"{row['first_name']} {row['last_name']}".strip()
                reminders.append((days_left, full_name, row["birthday"], row["phone"]))

        reminders.sort(key=lambda item: item[0])
        return reminders

    def close(self) -> None:
        self.conn.close()


class ForgotPasswordDialog(tk.Toplevel):
    def __init__(self, parent, db: ContactDatabase):
        super().__init__(parent)
        self.db = db
        self.title("Forgot Password")
        self.geometry("460x320")
        self.resizable(False, False)
        self.configure(bg=THEME["bg"])
        self.transient(parent)
        self.grab_set()

        card = tk.Frame(
            self,
            bg=THEME["surface"],
            padx=20,
            pady=16,
            highlightbackground="#d8e4f0",
            highlightthickness=1,
        )
        card.pack(fill="both", expand=True, padx=18, pady=18)

        tk.Label(
            card,
            text="Reset Password",
            font=("Segoe UI", 13, "bold"),
            bg=THEME["surface"],
            fg=THEME["primary_dark"],
        ).grid(row=0, column=0, columnspan=2, pady=(0, 10), sticky="w")

        tk.Label(card, text="Username", bg=THEME["surface"], fg=THEME["text"]).grid(
            row=1, column=0, sticky="w", pady=6
        )
        self.username_entry = tk.Entry(card, width=30, relief="solid", bd=1)
        self.username_entry.grid(row=1, column=1, sticky="w")

        tk.Label(card, text="Security Answer", bg=THEME["surface"], fg=THEME["text"]).grid(
            row=2, column=0, sticky="w", pady=6
        )
        self.security_entry = tk.Entry(card, width=30, relief="solid", bd=1)
        self.security_entry.grid(row=2, column=1, sticky="w")

        tk.Label(card, text="New Password", bg=THEME["surface"], fg=THEME["text"]).grid(
            row=3, column=0, sticky="w", pady=6
        )
        self.new_password_entry = tk.Entry(card, width=30, show="*", relief="solid", bd=1)
        self.new_password_entry.grid(row=3, column=1, sticky="w")

        tk.Label(card, text="Confirm Password", bg=THEME["surface"], fg=THEME["text"]).grid(
            row=4, column=0, sticky="w", pady=6
        )
        self.confirm_password_entry = tk.Entry(card, width=30, show="*", relief="solid", bd=1)
        self.confirm_password_entry.grid(row=4, column=1, sticky="w")

        tk.Button(
            card,
            text="Reset Password",
            width=18,
            command=self.reset_password,
            bg=THEME["accent"],
            fg="white",
            relief="flat",
        ).grid(row=5, column=0, columnspan=2, pady=(12, 6))

        tk.Label(
            card,
            text="Default security answer for admin: mkce",
            bg=THEME["surface"],
            fg=THEME["muted"],
        ).grid(row=6, column=0, columnspan=2, sticky="w")

    def reset_password(self) -> None:
        username = self.username_entry.get().strip()
        security_answer = self.security_entry.get().strip()
        new_password = self.new_password_entry.get().strip()
        confirm = self.confirm_password_entry.get().strip()

        if not username or not security_answer or not new_password or not confirm:
            messagebox.showerror("Error", "All fields are required.", parent=self)
            return

        if new_password != confirm:
            messagebox.showerror("Error", "Password and confirm password do not match.", parent=self)
            return

        if len(new_password) < 4:
            messagebox.showerror("Error", "Password must be at least 4 characters.", parent=self)
            return

        if self.db.reset_password(username, security_answer, new_password):
            messagebox.showinfo("Success", "Password reset successful.", parent=self)
            self.destroy()
        else:
            messagebox.showerror(
                "Error", "Username or security answer is incorrect.", parent=self
            )


class LoginPage(tk.Frame):
    def __init__(self, parent, db: ContactDatabase, on_login):
        super().__init__(parent, bg=THEME["bg"])
        self.db = db
        self.on_login = on_login
        self._build_ui()

    def _build_ui(self) -> None:
        banner = tk.Frame(self, bg=THEME["primary"], height=150)
        banner.pack(fill="x")
        banner.pack_propagate(False)
        tk.Label(
            banner,
            text="Smart Contact Management",
            font=("Segoe UI", 20, "bold"),
            fg="white",
            bg=THEME["primary"],
        ).pack(anchor="w", padx=30, pady=(30, 6))
        tk.Label(
            banner,
            text="Secure login, quick search, and modern contact organization",
            font=("Segoe UI", 10),
            fg="#d4e9ff",
            bg=THEME["primary"],
        ).pack(anchor="w", padx=30)

        content = tk.Frame(self, bg=THEME["bg"], padx=35, pady=24)
        content.pack(fill="both", expand=True)

        info_card = tk.Frame(
            content,
            bg=THEME["surface_soft"],
            padx=24,
            pady=24,
            highlightbackground="#c6dbf5",
            highlightthickness=1,
        )
        info_card.pack(side="left", fill="both", expand=True, padx=(0, 16))

        tk.Label(
            info_card,
            text="Welcome Back",
            font=("Segoe UI", 17, "bold"),
            bg=THEME["surface_soft"],
            fg=THEME["primary_dark"],
        ).pack(anchor="w")
        tk.Label(
            info_card,
            text="Keep all personal and professional contacts in one place.",
            font=("Segoe UI", 10),
            bg=THEME["surface_soft"],
            fg=THEME["muted"],
            wraplength=360,
            justify="left",
        ).pack(anchor="w", pady=(8, 16))

        highlights = [
            "Fast add, update, and delete contacts",
            "Birthday and emergency reminders",
            "LinkedIn ID, GitHub ID, and address tracking",
        ]
        for line in highlights:
            tk.Label(
                info_card,
                text=f"• {line}",
                font=("Segoe UI", 10),
                bg=THEME["surface_soft"],
                fg=THEME["text"],
            ).pack(anchor="w", pady=3)

        login_card = tk.Frame(
            content,
            bg=THEME["surface"],
            padx=25,
            pady=20,
            highlightbackground="#d8e4f0",
            highlightthickness=1,
        )
        login_card.pack(side="left", padx=(8, 0))

        tk.Label(
            login_card,
            text="Contact Management Login",
            font=("Segoe UI", 15, "bold"),
            bg=THEME["surface"],
            fg=THEME["primary_dark"],
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 14))

        tk.Label(login_card, text="Username", bg=THEME["surface"], fg=THEME["text"]).grid(
            row=1, column=0, sticky="w", pady=6
        )
        self.username_entry = tk.Entry(login_card, width=30, relief="solid", bd=1)
        self.username_entry.grid(row=1, column=1, pady=6)

        tk.Label(login_card, text="Password", bg=THEME["surface"], fg=THEME["text"]).grid(
            row=2, column=0, sticky="w", pady=6
        )
        self.password_entry = tk.Entry(login_card, width=30, show="*", relief="solid", bd=1)
        self.password_entry.grid(row=2, column=1, pady=6)
        self.password_entry.bind("<Return>", lambda _event: self.login())

        tk.Button(
            login_card,
            text="Login",
            width=16,
            command=self.login,
            bg=THEME["primary"],
            fg="white",
            relief="flat",
        ).grid(row=3, column=0, columnspan=2, pady=(12, 4))

        tk.Button(
            login_card,
            text="Forgot Password?",
            command=self.open_forgot_password,
            relief="flat",
            fg=THEME["primary"],
            bg=THEME["surface"],
            cursor="hand2",
        ).grid(row=4, column=0, columnspan=2, pady=(0, 8))

        tk.Label(
            login_card,
            text="Default: username=admin, password=admin123",
            bg=THEME["surface"],
            fg=THEME["muted"],
        ).grid(row=5, column=0, columnspan=2, sticky="w")

        self.username_entry.focus_set()

    def login(self) -> None:
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()

        if not username or not password:
            messagebox.showerror("Login Failed", "Enter username and password.")
            return

        if self.db.validate_login(username, password):
            self.on_login(username)
        else:
            messagebox.showerror("Login Failed", "Invalid username or password.")

    def open_forgot_password(self) -> None:
        ForgotPasswordDialog(self, self.db)


class ContactManagerPage(tk.Frame):
    def __init__(self, parent, db: ContactDatabase, username: str, on_logout):
        super().__init__(parent, bg=THEME["bg"])
        self.db = db
        self.username = username
        self.on_logout = on_logout
        self.selected_contact_id = None
        self._build_ui()
        self.load_contacts()

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg=THEME["primary"], height=68)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(
            header,
            text="Smart Contact Management System",
            font=("Segoe UI", 16, "bold"),
            bg=THEME["primary"],
            fg="white",
        ).pack(side="left", padx=18)

        tk.Label(
            header,
            text=f"Logged in: {self.username}",
            bg=THEME["primary"],
            fg="#d4e9ff",
            font=("Segoe UI", 10, "bold"),
        ).pack(side="right", padx=(0, 10), pady=20)

        tk.Button(
            header,
            text="Logout",
            command=self.on_logout,
            width=10,
            bg="#f7fafc",
            fg=THEME["primary_dark"],
            relief="flat",
            cursor="hand2",
        ).pack(side="right", padx=12, pady=16)

        body = tk.Frame(self, bg=THEME["bg"])
        body.pack(fill="both", expand=True, padx=14, pady=12)

        left_panel = tk.Frame(
            body,
            bg=THEME["surface"],
            padx=14,
            pady=14,
            highlightbackground="#d8e4f0",
            highlightthickness=1,
        )
        left_panel.pack(side="left", fill="y", expand=False, padx=(0, 10))
        tk.Label(
            left_panel,
            text="Contact Details",
            bg=THEME["surface"],
            fg=THEME["primary_dark"],
            font=("Segoe UI", 13, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        self.entries = {}
        fields = [
            ("First Name", "first_name"),
            ("Last Name", "last_name"),
            ("Phone", "phone"),
            ("Email", "email"),
            ("Birthday (DD-MM-YYYY)", "birthday"),
            ("LinkedIn ID", "linkedin_id"),
            ("GitHub ID", "github_id"),
        ]

        for row_index, (label, key) in enumerate(fields, start=1):
            tk.Label(
                left_panel, text=label, bg=THEME["surface"], fg=THEME["text"], font=("Segoe UI", 10)
            ).grid(
                row=row_index, column=0, sticky="w", pady=4
            )
            entry = tk.Entry(
                left_panel,
                width=31,
                relief="solid",
                bd=1,
                highlightthickness=1,
                highlightbackground="#d2dbe8",
                highlightcolor=THEME["primary"],
            )
            entry.grid(row=row_index, column=1, pady=4, padx=(8, 0), sticky="w")
            self.entries[key] = entry

        tk.Label(left_panel, text="Address", bg=THEME["surface"], fg=THEME["text"]).grid(
            row=8, column=0, sticky="nw", pady=4
        )
        self.address_text = tk.Text(
            left_panel,
            width=30,
            height=3,
            relief="solid",
            bd=1,
            highlightthickness=1,
            highlightbackground="#d2dbe8",
            highlightcolor=THEME["primary"],
        )
        self.address_text.grid(row=8, column=1, pady=4, padx=(8, 0), sticky="w")

        tk.Label(left_panel, text="Notes", bg=THEME["surface"], fg=THEME["text"]).grid(
            row=9, column=0, sticky="nw", pady=4
        )
        self.notes_text = tk.Text(
            left_panel,
            width=30,
            height=4,
            relief="solid",
            bd=1,
            highlightthickness=1,
            highlightbackground="#d2dbe8",
            highlightcolor=THEME["primary"],
        )
        self.notes_text.grid(row=9, column=1, pady=4, padx=(8, 0), sticky="w")

        self.emergency_var = tk.IntVar(value=0)
        tk.Checkbutton(
            left_panel,
            text="Emergency Contact",
            bg=THEME["surface"],
            fg=THEME["text"],
            activebackground=THEME["surface"],
            selectcolor=THEME["surface"],
            variable=self.emergency_var,
            onvalue=1,
            offvalue=0,
        ).grid(row=10, column=0, columnspan=2, sticky="w", pady=8)

        self.birthday_reminder_var = tk.IntVar(value=1)
        tk.Checkbutton(
            left_panel,
            text="Birthday Reminder",
            bg=THEME["surface"],
            fg=THEME["text"],
            activebackground=THEME["surface"],
            selectcolor=THEME["surface"],
            variable=self.birthday_reminder_var,
            onvalue=1,
            offvalue=0,
        ).grid(row=11, column=0, columnspan=2, sticky="w", pady=(0, 8))

        right_panel = tk.Frame(
            body,
            bg=THEME["surface"],
            highlightbackground="#d8e4f0",
            highlightthickness=1,
            padx=10,
            pady=10,
        )
        right_panel.pack(side="right", fill="both", expand=True)
        tk.Label(
            right_panel,
            text="Contacts",
            bg=THEME["surface"],
            fg=THEME["primary_dark"],
            font=("Segoe UI", 13, "bold"),
        ).pack(anchor="w", pady=(0, 8))

        columns = (
            "id",
            "name",
            "phone",
            "email",
            "birthday",
            "linkedin",
            "github",
            "address",
            "emergency",
        )
        table_wrap = tk.Frame(right_panel, bg=THEME["surface"])
        table_wrap.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(table_wrap, columns=columns, show="headings", height=17)
        self.tree.heading("id", text="ID")
        self.tree.heading("name", text="Name")
        self.tree.heading("phone", text="Phone")
        self.tree.heading("email", text="Email")
        self.tree.heading("birthday", text="Birthday")
        self.tree.heading("linkedin", text="LinkedIn ID")
        self.tree.heading("github", text="GitHub ID")
        self.tree.heading("address", text="Address")
        self.tree.heading("emergency", text="Emergency")
        self.tree.column("id", width=40, anchor="center")
        self.tree.column("name", width=150)
        self.tree.column("phone", width=100)
        self.tree.column("email", width=160)
        self.tree.column("birthday", width=95, anchor="center")
        self.tree.column("linkedin", width=130)
        self.tree.column("github", width=120)
        self.tree.column("address", width=240)
        self.tree.column("emergency", width=85, anchor="center")

        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_select_contact)

        scrollbar_y = ttk.Scrollbar(table_wrap, orient="vertical", command=self.tree.yview)
        scrollbar_y.pack(side="right", fill="y")
        scrollbar_x = ttk.Scrollbar(right_panel, orient="horizontal", command=self.tree.xview)
        scrollbar_x.pack(fill="x", pady=(4, 0))
        self.tree.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)

        controls = tk.Frame(
            self,
            bg=THEME["surface"],
            highlightbackground="#d8e4f0",
            highlightthickness=1,
            padx=10,
            pady=10,
        )
        controls.pack(fill="x", padx=12, pady=(0, 12))

        top_buttons = tk.Frame(controls, bg=THEME["surface"])
        top_buttons.pack(fill="x", pady=(0, 8))
        tk.Button(
            top_buttons,
            text="Add",
            width=13,
            command=self.add_contact,
            bg=THEME["accent"],
            fg="white",
            relief="flat",
            cursor="hand2",
        ).pack(side="left", padx=5)
        tk.Button(
            top_buttons,
            text="Update",
            width=13,
            command=self.update_contact,
            bg=THEME["primary"],
            fg="white",
            relief="flat",
            cursor="hand2",
        ).pack(side="left", padx=5)
        tk.Button(
            top_buttons,
            text="Delete",
            width=13,
            command=self.delete_contact,
            bg=THEME["danger"],
            fg="white",
            relief="flat",
            cursor="hand2",
        ).pack(side="left", padx=5)
        tk.Button(
            top_buttons,
            text="Show All",
            width=13,
            command=self.show_all_contacts,
            bg=THEME["surface_soft"],
            fg=THEME["primary_dark"],
            relief="flat",
            cursor="hand2",
        ).pack(side="left", padx=5)
        tk.Button(
            top_buttons,
            text="Clear",
            width=13,
            command=self.clear_form,
            bg=THEME["surface_soft"],
            fg=THEME["primary_dark"],
            relief="flat",
            cursor="hand2",
        ).pack(side="left", padx=5)

        bottom_buttons = tk.Frame(controls, bg=THEME["surface"])
        bottom_buttons.pack(fill="x")
        self.search_var = tk.StringVar()
        search_entry = tk.Entry(
            bottom_buttons,
            textvariable=self.search_var,
            width=26,
            relief="solid",
            bd=1,
            highlightthickness=1,
            highlightbackground="#d2dbe8",
            highlightcolor=THEME["primary"],
        )
        search_entry.pack(side="left", padx=5)
        tk.Button(
            bottom_buttons,
            text="Search",
            width=13,
            command=self.search_contacts,
            bg=THEME["primary"],
            fg="white",
            relief="flat",
            cursor="hand2",
        ).pack(side="left", padx=5)
        tk.Button(
            bottom_buttons,
            text="Birthday Reminder",
            width=18,
            command=self.show_birthday_reminders,
            bg=THEME["surface_soft"],
            fg=THEME["primary_dark"],
            relief="flat",
            cursor="hand2",
        ).pack(side="left", padx=5)
        tk.Button(
            bottom_buttons,
            text="Emergency Contacts",
            width=18,
            command=self.show_emergency_contacts,
            bg=THEME["surface_soft"],
            fg=THEME["primary_dark"],
            relief="flat",
            cursor="hand2",
        ).pack(side="left", padx=5)
        tk.Button(
            bottom_buttons,
            text="Show Notes",
            width=13,
            command=self.show_notes,
            bg=THEME["surface_soft"],
            fg=THEME["primary_dark"],
            relief="flat",
            cursor="hand2",
        ).pack(side="left", padx=5)

    def _validate_birthday(self, value: str) -> bool:
        if not value:
            return True
        try:
            datetime.strptime(value, "%d-%m-%Y")
            return True
        except ValueError:
            return False

    def _get_form_data(self) -> dict:
        return {
            "first_name": self.entries["first_name"].get().strip(),
            "last_name": self.entries["last_name"].get().strip(),
            "phone": self.entries["phone"].get().strip(),
            "email": self.entries["email"].get().strip(),
            "birthday": self.entries["birthday"].get().strip(),
            "notes": self.notes_text.get("1.0", tk.END).strip(),
            "emergency": self.emergency_var.get(),
            "birthday_reminder": self.birthday_reminder_var.get(),
            "linkedin_id": self.entries["linkedin_id"].get().strip(),
            "github_id": self.entries["github_id"].get().strip(),
            "address": self.address_text.get("1.0", tk.END).strip(),
        }

    def clear_form(self, clear_selection: bool = True) -> None:
        for entry in self.entries.values():
            entry.delete(0, tk.END)
        self.address_text.delete("1.0", tk.END)
        self.notes_text.delete("1.0", tk.END)
        self.emergency_var.set(0)
        self.birthday_reminder_var.set(1)
        self.selected_contact_id = None
        if clear_selection:
            self.tree.selection_remove(self.tree.selection())

    def load_contacts(self, keyword: str = "", emergency_only: bool = False) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)

        contacts = self.db.get_contacts(keyword=keyword, emergency_only=emergency_only)
        for row in contacts:
            full_name = f"{row['first_name']} {row['last_name']}".strip()
            emergency_label = "Yes" if row["emergency"] else "No"
            self.tree.insert(
                "",
                tk.END,
                values=(
                    row["id"],
                    full_name,
                    row["phone"] or "",
                    row["email"] or "",
                    row["birthday"] or "",
                    row["linkedin_id"] or "",
                    row["github_id"] or "",
                    row["address"] or "",
                    emergency_label,
                ),
            )

    def add_contact(self) -> None:
        data = self._get_form_data()
        if not data["first_name"] or not data["phone"]:
            messagebox.showerror("Error", "First Name and Phone are required.")
            return
        if not self._validate_birthday(data["birthday"]):
            messagebox.showerror("Error", "Birthday must be in DD-MM-YYYY format.")
            return

        self.db.add_contact(data)
        self.load_contacts()
        self.clear_form()
        messagebox.showinfo("Success", "Contact added!")

    def update_contact(self) -> None:
        if not self.selected_contact_id:
            messagebox.showwarning("Warning", "Select a contact to update.")
            return

        data = self._get_form_data()
        if not data["first_name"] or not data["phone"]:
            messagebox.showerror("Error", "First Name and Phone are required.")
            return
        if not self._validate_birthday(data["birthday"]):
            messagebox.showerror("Error", "Birthday must be in DD-MM-YYYY format.")
            return

        self.db.update_contact(self.selected_contact_id, data)
        self.load_contacts()
        messagebox.showinfo("Success", "Contact updated!")

    def delete_contact(self) -> None:
        if not self.selected_contact_id:
            messagebox.showwarning("Warning", "Select a contact to delete.")
            return

        should_delete = messagebox.askyesno(
            "Confirm Delete", "Are you sure you want to delete this contact?"
        )
        if not should_delete:
            return

        self.db.delete_contact(self.selected_contact_id)
        self.load_contacts()
        self.clear_form()
        messagebox.showinfo("Success", "Contact deleted!")

    def show_all_contacts(self) -> None:
        self.search_var.set("")
        self.load_contacts()

    def search_contacts(self) -> None:
        keyword = self.search_var.get().strip()
        self.load_contacts(keyword=keyword)

    def show_emergency_contacts(self) -> None:
        self.load_contacts(emergency_only=True)

    def show_birthday_reminders(self) -> None:
        reminders = self.db.get_upcoming_birthdays(days_ahead=30)
        if not reminders:
            messagebox.showinfo("Birthday Reminder", "No upcoming birthdays in next 30 days.")
            return

        lines = []
        for days_left, full_name, birthday, phone in reminders:
            when = "Today" if days_left == 0 else f"In {days_left} day(s)"
            lines.append(f"{full_name} - {birthday} - {phone} ({when})")

        messagebox.showinfo("Birthday Reminder", "\n".join(lines))

    def on_select_contact(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            return

        item = self.tree.item(selection[0], "values")
        self.selected_contact_id = int(item[0])
        row = self.db.get_contact(self.selected_contact_id)
        if row is None:
            return

        self.clear_form(clear_selection=False)
        self.selected_contact_id = row["id"]
        self.entries["first_name"].insert(0, row["first_name"] or "")
        self.entries["last_name"].insert(0, row["last_name"] or "")
        self.entries["phone"].insert(0, row["phone"] or "")
        self.entries["email"].insert(0, row["email"] or "")
        self.entries["birthday"].insert(0, row["birthday"] or "")
        self.entries["linkedin_id"].insert(0, row["linkedin_id"] or "")
        self.entries["github_id"].insert(0, row["github_id"] or "")
        self.address_text.insert("1.0", row["address"] or "")
        self.notes_text.insert("1.0", row["notes"] or "")
        self.emergency_var.set(row["emergency"] or 0)
        self.birthday_reminder_var.set(row["birthday_reminder"] if row["birthday_reminder"] is not None else 1)

    def show_notes(self) -> None:
        if not self.selected_contact_id:
            messagebox.showwarning("Warning", "Select a contact first.")
            return
        row = self.db.get_contact(self.selected_contact_id)
        if row is None:
            return

        full_name = f"{row['first_name']} {row['last_name']}".strip()
        notes = row["notes"] or "No notes available."
        address = row["address"] or "No address available."
        linkedin_id = row["linkedin_id"] or "N/A"
        github_id = row["github_id"] or "N/A"
        messagebox.showinfo(
            "Contact Details",
            (
                f"{full_name}\n\nLinkedIn ID: {linkedin_id}\nGitHub ID: {github_id}"
                f"\n\nAddress:\n{address}\n\nNotes:\n{notes}"
            ),
        )


class ContactManagementApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Smart Contact Management System")
        self.geometry("1240x760")
        self.configure(bg=THEME["bg"])
        self.minsize(1080, 660)
        self._configure_ttk_theme()
        self.db = ContactDatabase(DB_NAME)
        self.current_frame = None
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.show_login()

    def _configure_ttk_theme(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "Treeview",
            background=THEME["surface"],
            foreground=THEME["text"],
            fieldbackground=THEME["surface"],
            rowheight=30,
            font=("Segoe UI", 9),
        )
        style.map("Treeview", background=[("selected", "#d9ebff")], foreground=[("selected", THEME["text"])])
        style.configure(
            "Treeview.Heading",
            background=THEME["primary"],
            foreground="white",
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padding=(6, 5),
        )

    def _set_frame(self, frame: tk.Frame) -> None:
        if self.current_frame is not None:
            self.current_frame.destroy()
        self.current_frame = frame
        self.current_frame.pack(fill="both", expand=True)

    def show_login(self) -> None:
        self._set_frame(LoginPage(self, self.db, self.login_success))

    def login_success(self, username: str) -> None:
        self._set_frame(ContactManagerPage(self, self.db, username, self.show_login))

    def on_close(self) -> None:
        self.db.close()
        self.destroy()


if __name__ == "__main__":
    app = ContactManagementApp()
    app.mainloop()
