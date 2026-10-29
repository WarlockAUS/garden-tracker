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

BANANA_CATALOG_ENTRY = {
    "name": "Banana",
    "npk_ratio": "Target ratio approx. 3 : 1 : 6 (N : P2O5 : K2O).\nMineral blend: 365g Sulphate of Ammonia (21% N) : 270g Superphosphate (9.1% P2O5) : 365g Sulphate of Potash (41.5% K2O) per 1kg batch.\nResulting analysis: ~7.67% N, 2.46% P2O5, 15.15% K2O.",
    "dosing_rules": "Start at 50g of blend per clump per application.\nFrequency: every 4-6 weeks while actively growing.\nSpread thinly across the wider root zone, not a tight ring.\nApply to moist soil, water in gently afterwards.\nReduce or pause over winter if growth visibly slows.\nHold at 50g for at least a full season before increasing. Only raise if plant shows strong healthy growth with no leaf scorch or wilting.",
    "seasonal_notes": "Spring-Summer: feed every 4-6 weeks, 50g.\nAutumn: taper to 30-50g.\nWinter: pause feeding unless still actively growing. Soil test before applying dolomite. Keep dolomite 2-3 weeks clear of any sulphate of ammonia application.\nSpring: resume full feeding 2-3 weeks clear of any winter dolomite.",
    "deficiency_guide": "Yellowing between veins, veins stay green, older/lower leaves: Magnesium deficiency - check soil test, consider Epsom salts.\nGeneral pale yellowing, slow growth: Nitrogen deficiency.\nDark green leaves, weak stems, poor bunch fill: Potassium deficiency.\nBrown scorched leaf margins, wilting after feeding: Over-fertilising, reduce dose.\nPurplish/reddish leaf tinge: Phosphorus deficiency (less common).",
    "mulch_notes": "Depth: approx 10cm of organic mulch (banana leaves, sugarcane, pea straw, aged wood chips).\nKeep a few cm clear of the stems to avoid collar rot.\nSequence: pull mulch back, apply fertiliser to moist soil, water in, replace mulch.\nTop up every 2-3 months or when sparse.\nSucker thinning: keep main stem plus 1-2 follower suckers, remove extras at ground level while small.",
}


def get_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS plant_catalog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            npk_ratio TEXT,
            dosing_rules TEXT,
            seasonal_notes TEXT,
            deficiency_guide TEXT,
            mulch_notes TEXT
        )
        """
    )

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

    # Migrations for existing databases
    plant_columns = [row[1] for row in conn.execute("PRAGMA table_info(plants)")]
    if "catalog_id" not in plant_columns:
        conn.execute("ALTER TABLE plants ADD COLUMN catalog_id INTEGER")

    log_columns = [row[1] for row in conn.execute("PRAGMA table_info(log_entries)")]
    if "plant_id" not in log_columns:
        conn.execute("ALTER TABLE log_entries ADD COLUMN plant_id INTEGER")

    # Seed the Banana catalog entry if it doesn't exist yet
    existing = conn.execute(
        "SELECT id FROM plant_catalog WHERE name = ?", (BANANA_CATALOG_ENTRY["name"],)
    ).fetchone()
    if not existing:
        conn.execute(
            """
            INSERT INTO plant_catalog (name, npk_ratio, dosing_rules, seasonal_notes, deficiency_guide, mulch_notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                BANANA_CATALOG_ENTRY["name"],
                BANANA_CATALOG_ENTRY["npk_ratio"],
                BANANA_CATALOG_ENTRY["dosing_rules"],
                BANANA_CATALOG_ENTRY["seasonal_notes"],
                BANANA_CATALOG_ENTRY["deficiency_guide"],
                BANANA_CATALOG_ENTRY["mulch_notes"],
            ),
        )
        banana_catalog_id = conn.execute(
            "SELECT id FROM plant_catalog WHERE name = ?", (BANANA_CATALOG_ENTRY["name"],)
        ).fetchone()[0]
    else:
        banana_catalog_id = existing["id"]

    # Seed a default plant if none exist yet
    count = conn.execute("SELECT COUNT(*) FROM plants").fetchone()[0]
    if count == 0:
        conn.execute(
            "INSERT INTO plants (name, plant_type, catalog_id) VALUES (?, ?, ?)",
            ("Banana Clump", "Banana", banana_catalog_id),
        )

    # Link any existing plants with plant_type 'Banana' but no catalog_id yet
    conn.execute(
        "UPDATE plants SET catalog_id = ? WHERE plant_type = 'Banana' AND catalog_id IS NULL",
        (banana_catalog_id,),
    )

    conn.commit()
    conn.close()


def get_plants():
    conn = get_db()
    plants = conn.execute(
        """
        SELECT plants.*, plant_catalog.name AS catalog_name
        FROM plants
        LEFT JOIN plant_catalog ON plants.catalog_id = plant_catalog.id
        ORDER BY plants.name
        """
    ).fetchall()
    conn.close()
    return plants


def get_catalog():
    conn = get_db()
    catalog = conn.execute("SELECT * FROM plant_catalog ORDER BY name").fetchall()
    conn.close()
    return catalog


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
        catalog_id = request.form.get("catalog_id") or None
        if name:
            conn = get_db()
            conn.execute(
                "INSERT INTO plants (name, catalog_id) VALUES (?, ?)",
                (name, catalog_id),
            )
            conn.commit()
            conn.close()
        return redirect(url_for("manage_plants"))

    return render_template(
        "plants.html", plants=get_plants(), catalog=get_catalog()
    )


@app.route("/catalog")
def catalog_list():
    return render_template("catalog_list.html", catalog=get_catalog())


@app.route("/catalog/<int:catalog_id>")
def catalog_detail(catalog_id):
    conn = get_db()
    entry = conn.execute(
        "SELECT * FROM plant_catalog WHERE id = ?", (catalog_id,)
    ).fetchone()
    conn.close()
    return render_template("catalog_detail.html", entry=entry)


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000)
