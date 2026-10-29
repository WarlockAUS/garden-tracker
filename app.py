import sqlite3
import os
from datetime import date
from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)

DATA_DIR = "/app/data"
DB_PATH = os.path.join(DATA_DIR, "garden.db")

ACTION_TYPES = [
    "Feed",
    "Dolomite",
    "Epsom Salts",
    "Mulch",
    "Sucker Removal",
    "Watering",
    "Pest Treatment",
    "Other",
]

UNITS = ["grams", "handfuls", "litres", "barrow loads"]


def get_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS log_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_date TEXT NOT NULL,
            action_type TEXT NOT NULL,
            quantity REAL,
            unit TEXT,
            soil_ph REAL,
            notes TEXT
        )
        """
    )
    conn.commit()
    conn.close()


@app.route("/")
def log_list():
    conn = get_db()
    entries = conn.execute(
        "SELECT * FROM log_entries ORDER BY entry_date DESC, id DESC"
    ).fetchall()
    conn.close()
    return render_template("log_list.html", entries=entries)


@app.route("/add", methods=["GET", "POST"])
def add_entry():
    if request.method == "POST":
        entry_date = request.form.get("entry_date") or str(date.today())
        action_type = request.form.get("action_type")
        quantity = request.form.get("quantity") or None
        unit = request.form.get("unit") or None
        soil_ph = request.form.get("soil_ph") or None
        notes = request.form.get("notes") or ""

        conn = get_db()
        conn.execute(
            """
            INSERT INTO log_entries (entry_date, action_type, quantity, unit, soil_ph, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (entry_date, action_type, quantity, unit, soil_ph, notes),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("log_list"))

    return render_template(
        "log_form.html",
        action_types=ACTION_TYPES,
        units=UNITS,
        today=str(date.today()),
    )


@app.route("/delete/<int:entry_id>", methods=["POST"])
def delete_entry(entry_id):
    conn = get_db()
    conn.execute("DELETE FROM log_entries WHERE id = ?", (entry_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("log_list"))


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000)
