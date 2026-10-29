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
        CREATE TABLE IF NOT EXISTS plants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            plant_type TEXT
        )
        """
    )

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

    # Migration: add plant_id column to log_entries if it doesn't already exist
    existing_columns = [row[1] for row in conn.execute("PRAGMA table_info(log_entries)")]
    if "plant_id" not in existing_columns:
        conn.execute("ALTER TABLE log_entries ADD COLUMN plant_id INTEGER")

    # Seed a default plant if none exist yet, so old entries have somewhere to point
    count = conn.execute("SELECT COUNT(*) FROM plants").fetchone()[0]
    if count == 0:
        conn.execute(
            "INSERT INTO plants (name, plant_type) VALUES (?, ?)",
            ("Banana Clump", "Banana"),
        )

    conn.commit()
    conn.close()


def get_plants():
    conn = get_db()
    plants = conn.execute("SELECT * FROM plants ORDER BY name").fetchall()
    conn.close()
    return plants


@app.route("/")
def log_list():
    plant_filter = request.args.get("plant_id", "")
    conn = get_db()

    query = """
        SELECT log_entries.*, plants.name AS plant_name
        FROM log_entries
        LEFT JOIN plants ON log_entries.plant_id = plants.id
    """
    params = []
    if plant_filter:
        query += " WHERE log_entries.plant_id = ?"
        params.append(plant_filter)
    query += " ORDER BY entry_date DESC, log_entries.id DESC"

    entries = conn.execute(query, params).fetchall()
    plants = conn.execute("SELECT * FROM plants ORDER BY name").fetchall()
    conn.close()
    return render_template(
        "log_list.html", entries=entries, plants=plants, selected_plant=plant_filter
    )


@app.route("/add", methods=["GET", "POST"])
def add_entry():
    if request.method == "POST":
        entry_date = request.form.get("entry_date") or str(date.today())
        action_type = request.form.get("action_type")
        quantity = request.form.get("quantity") or None
        unit = request.form.get("unit") or None
        soil_ph = request.form.get("soil_ph") or None
        notes = request.form.get("notes") or ""
        plant_id = request.form.get("plant_id") or None

        conn = get_db()
        conn.execute(
            """
            INSERT INTO log_entries (entry_date, action_type, quantity, unit, soil_ph, notes, plant_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (entry_date, action_type, quantity, unit, soil_ph, notes, plant_id),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("log_list"))

    return render_template(
        "log_form.html",
        action_types=ACTION_TYPES,
        units=UNITS,
        today=str(date.today()),
        plants=get_plants(),
    )


@app.route("/delete/<int:entry_id>", methods=["POST"])
def delete_entry(entry_id):
    conn = get_db()
    conn.execute("DELETE FROM log_entries WHERE id = ?", (entry_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("log_list"))


@app.route("/plants", methods=["GET", "POST"])
def manage_plants():
    if request.method == "POST":
        name = request.form.get("name")
        plant_type = request.form.get("plant_type") or ""
        if name:
            conn = get_db()
            conn.execute(
                "INSERT INTO plants (name, plant_type) VALUES (?, ?)",
                (name, plant_type),
            )
            conn.commit()
            conn.close()
        return redirect(url_for("manage_plants"))

    return render_template("plants.html", plants=get_plants())


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000)
