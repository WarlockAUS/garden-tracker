import sqlite3
import os
import csv
import io
from datetime import date, datetime
from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)

DATA_DIR = "/app/data"
DB_PATH = os.path.join(DATA_DIR, "garden.db")

ACTION_TYPES = [
    "Feed", "Dolomite", "Epsom Salts", "Mulch",
    "Sucker Removal", "Watering", "Pest Treatment", "Other",
]

UNITS = ["grams", "handfuls", "litres", "barrow loads"]

CATALOG_FIELDS = ["name", "npk_ratio", "dosing_rules", "seasonal_notes", "deficiency_guide", "mulch_notes"]
CATALOG_FIELDS_WITH_FREQ = CATALOG_FIELDS + ["feed_frequency_days"]

BANANA_CATALOG_ENTRY = {
    "name": "Banana",
    "npk_ratio": "Target ratio approx. 3 : 1 : 6 (N : P2O5 : K2O).\nMineral blend: 365g Sulphate of Ammonia (21% N) : 270g Superphosphate (9.1% P2O5) : 365g Sulphate of Potash (41.5% K2O) per 1kg batch.\nResulting analysis: ~7.67% N, 2.46% P2O5, 15.15% K2O.",
    "dosing_rules": "Start at 50g of blend per clump per application.\nFrequency: every 4-6 weeks while actively growing.\nSpread thinly across the wider root zone, not a tight ring.\nApply to moist soil, water in gently afterwards.\nReduce or pause over winter if growth visibly slows.\nHold at 50g for at least a full season before increasing.",
    "seasonal_notes": "Spring-Summer: feed every 4-6 weeks, 50g.\nAutumn: taper to 30-50g.\nWinter: pause feeding unless still actively growing. Soil test before applying dolomite.\nSpring: resume full feeding 2-3 weeks clear of any winter dolomite.",
    "deficiency_guide": "Yellowing between veins, veins stay green: Magnesium deficiency.\nGeneral pale yellowing, slow growth: Nitrogen deficiency.\nDark green leaves, weak stems, poor bunch fill: Potassium deficiency.\nBrown scorched leaf margins, wilting: Over-fertilising.\nPurplish/reddish leaf tinge: Phosphorus deficiency.",
    "mulch_notes": "Depth: approx 10cm organic mulch. Keep clear of stems.\nSequence: pull mulch back, apply fertiliser, water in, replace mulch.\nTop up every 2-3 months.\nSucker thinning: keep main stem plus 1-2 followers, remove extras while small.",
    "feed_frequency_days": 42,
}


def get_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS plant_catalog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            npk_ratio TEXT,
            dosing_rules TEXT,
            seasonal_notes TEXT,
            deficiency_guide TEXT,
            mulch_notes TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS plants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            plant_type TEXT,
            catalog_id INTEGER
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS log_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_date TEXT NOT NULL,
            action_type TEXT NOT NULL,
            quantity REAL,
            unit TEXT,
            soil_ph REAL,
            notes TEXT,
            plant_id INTEGER
        )
    """)

    plant_columns = [row[1] for row in conn.execute("PRAGMA table_info(plants)")]
    if "catalog_id" not in plant_columns:
        conn.execute("ALTER TABLE plants ADD COLUMN catalog_id INTEGER")

    log_columns = [row[1] for row in conn.execute("PRAGMA table_info(log_entries)")]
    if "plant_id" not in log_columns:
        conn.execute("ALTER TABLE log_entries ADD COLUMN plant_id INTEGER")

    catalog_columns = [row[1] for row in conn.execute("PRAGMA table_info(plant_catalog)")]
    if "feed_frequency_days" not in catalog_columns:
        conn.execute("ALTER TABLE plant_catalog ADD COLUMN feed_frequency_days INTEGER")

    existing = conn.execute(
        "SELECT id FROM plant_catalog WHERE name = ?", (BANANA_CATALOG_ENTRY["name"],)
    ).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO plant_catalog (name, npk_ratio, dosing_rules, seasonal_notes, deficiency_guide, mulch_notes, feed_frequency_days) VALUES (?, ?, ?, ?, ?, ?, ?)",
            tuple(BANANA_CATALOG_ENTRY[f] for f in CATALOG_FIELDS_WITH_FREQ),
        )
        banana_catalog_id = conn.execute(
            "SELECT id FROM plant_catalog WHERE name = ?", (BANANA_CATALOG_ENTRY["name"],)
        ).fetchone()[0]
    else:
        banana_catalog_id = existing["id"]
        conn.execute(
            "UPDATE plant_catalog SET feed_frequency_days = ? WHERE id = ? AND feed_frequency_days IS NULL",
            (BANANA_CATALOG_ENTRY["feed_frequency_days"], banana_catalog_id),
        )

    count = conn.execute("SELECT COUNT(*) FROM plants").fetchone()[0]
    if count == 0:
        conn.execute(
            "INSERT INTO plants (name, plant_type, catalog_id) VALUES (?, ?, ?)",
            ("Banana Clump", "Banana", banana_catalog_id),
        )

    conn.execute(
        "UPDATE plants SET catalog_id = ? WHERE plant_type = 'Banana' AND catalog_id IS NULL",
        (banana_catalog_id,),
    )

    conn.commit()
    conn.close()


def get_plants():
    conn = get_db()
    plants = conn.execute("""
        SELECT plants.*, plant_catalog.name AS catalog_name
        FROM plants LEFT JOIN plant_catalog ON plants.catalog_id = plant_catalog.id
        ORDER BY plants.name
    """).fetchall()
    conn.close()
    return plants


def get_catalog():
    conn = get_db()
    catalog = conn.execute("SELECT * FROM plant_catalog ORDER BY name").fetchall()
    conn.close()
    return catalog


def get_dashboard_data():
    conn = get_db()
    plants = conn.execute("""
        SELECT plants.id, plants.name, plant_catalog.name AS catalog_name,
               plant_catalog.feed_frequency_days
        FROM plants LEFT JOIN plant_catalog ON plants.catalog_id = plant_catalog.id
        ORDER BY plants.name
    """).fetchall()

    results = []
    today = date.today()

    for p in plants:
        last_feed = conn.execute(
            """
            SELECT entry_date FROM log_entries
            WHERE plant_id = ? AND action_type = 'Feed'
            ORDER BY entry_date DESC LIMIT 1
            """,
            (p["id"],),
        ).fetchone()

        status = "unknown"
        days_since = None
        last_feed_date = None

        if last_feed:
            last_feed_date = last_feed["entry_date"]
            try:
                parsed = datetime.strptime(last_feed_date, "%Y-%m-%d").date()
                days_since = (today - parsed).days
            except ValueError:
                days_since = None

        if p["feed_frequency_days"] is None:
            status = "no_schedule"
        elif days_since is None:
            status = "never_fed"
        elif days_since > p["feed_frequency_days"]:
            status = "overdue"
        elif days_since >= (p["feed_frequency_days"] - 7):
            status = "due_soon"
        else:
            status = "ok"

        results.append({
            "plant_id": p["id"],
            "plant_name": p["name"],
            "catalog_name": p["catalog_name"],
            "frequency_days": p["feed_frequency_days"],
            "last_feed_date": last_feed_date,
            "days_since": days_since,
            "status": status,
        })

    conn.close()
    return results


@app.route("/")
def dashboard():
    data = get_dashboard_data()
    return render_template("dashboard.html", data=data)


@app.route("/log")
def log_list():
    plant_filter = request.args.get("plant_id", "")
    action_filter = request.args.get("action_type", "")
    conn = get_db()
    query = """
        SELECT log_entries.*, plants.name AS plant_name
        FROM log_entries LEFT JOIN plants ON log_entries.plant_id = plants.id
        WHERE 1=1
    """
    params = []
    if plant_filter:
        query += " AND log_entries.plant_id = ?"
        params.append(plant_filter)
    if action_filter:
        query += " AND log_entries.action_type = ?"
        params.append(action_filter)
    query += " ORDER BY entry_date DESC, log_entries.id DESC"
    entries = conn.execute(query, params).fetchall()
    plants = conn.execute("SELECT * FROM plants ORDER BY name").fetchall()
    conn.close()
    return render_template(
        "log_list.html", entries=entries, plants=plants,
        selected_plant=plant_filter, selected_action=action_filter,
        action_types=ACTION_TYPES,
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
            "INSERT INTO log_entries (entry_date, action_type, quantity, unit, soil_ph, notes, plant_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (entry_date, action_type, quantity, unit, soil_ph, notes, plant_id),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("log_list"))

    return render_template("log_form.html", action_types=ACTION_TYPES, units=UNITS, today=str(date.today()), plants=get_plants())


@app.route("/edit/<int:entry_id>", methods=["GET", "POST"])
def edit_entry(entry_id):
    conn = get_db()
    if request.method == "POST":
        entry_date = request.form.get("entry_date")
        action_type = request.form.get("action_type")
        quantity = request.form.get("quantity") or None
        unit = request.form.get("unit") or None
        soil_ph = request.form.get("soil_ph") or None
        notes = request.form.get("notes") or ""
        plant_id = request.form.get("plant_id") or None

        conn.execute(
            """
            UPDATE log_entries
            SET entry_date=?, action_type=?, quantity=?, unit=?, soil_ph=?, notes=?, plant_id=?
            WHERE id=?
            """,
            (entry_date, action_type, quantity, unit, soil_ph, notes, plant_id, entry_id),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("log_list"))

    entry = conn.execute("SELECT * FROM log_entries WHERE id = ?", (entry_id,)).fetchone()
    plants = get_plants()
    conn.close()
    return render_template(
        "log_form.html", action_types=ACTION_TYPES, units=UNITS,
        today=str(date.today()), plants=plants, entry=entry, edit_mode=True,
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
            conn.execute("INSERT INTO plants (name, catalog_id) VALUES (?, ?)", (name, catalog_id))
            conn.commit()
            conn.close()
        return redirect(url_for("manage_plants"))

    return render_template("plants.html", plants=get_plants(), catalog=get_catalog())


@app.route("/catalog")
def catalog_list():
    return render_template("catalog_list.html", catalog=get_catalog())


@app.route("/catalog/<int:catalog_id>")
def catalog_detail(catalog_id):
    conn = get_db()
    entry = conn.execute("SELECT * FROM plant_catalog WHERE id = ?", (catalog_id,)).fetchone()
    conn.close()
    return render_template("catalog_detail.html", entry=entry)


@app.route("/catalog/edit/<int:catalog_id>", methods=["GET", "POST"])
def catalog_edit(catalog_id):
    conn = get_db()

    if request.method == "POST":
        values = [request.form.get(f, "") for f in CATALOG_FIELDS[1:]]  # skip name, not editable here
        freq = request.form.get("feed_frequency_days") or None

        conn.execute(
            """
            UPDATE plant_catalog
            SET npk_ratio=?, dosing_rules=?, seasonal_notes=?, deficiency_guide=?, mulch_notes=?, feed_frequency_days=?
            WHERE id=?
            """,
            (*values, freq, catalog_id),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("catalog_detail", catalog_id=catalog_id))

    entry = conn.execute("SELECT * FROM plant_catalog WHERE id = ?", (catalog_id,)).fetchone()
    conn.close()
    return render_template("catalog_edit.html", entry=entry)


@app.route("/catalog/add", methods=["GET", "POST"])
def catalog_add():
    if request.method == "POST":
        values = [request.form.get(f, "") for f in CATALOG_FIELDS]
        freq = request.form.get("feed_frequency_days") or None
        values.append(freq)
        conn = get_db()
        conn.execute(
            """
            INSERT INTO plant_catalog (name, npk_ratio, dosing_rules, seasonal_notes, deficiency_guide, mulch_notes, feed_frequency_days)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                npk_ratio=excluded.npk_ratio,
                dosing_rules=excluded.dosing_rules,
                seasonal_notes=excluded.seasonal_notes,
                deficiency_guide=excluded.deficiency_guide,
                mulch_notes=excluded.mulch_notes,
                feed_frequency_days=excluded.feed_frequency_days
            """,
            values,
        )
        conn.commit()
        conn.close()
        return redirect(url_for("catalog_list"))

    return render_template("catalog_add.html")


@app.route("/catalog/import", methods=["GET", "POST"])
def catalog_import():
    if request.method == "POST":
        action = request.form.get("action")

        if action == "preview":
            file = request.files.get("csv_file")
            if not file:
                return render_template("catalog_import.html", error="No file selected.", rows=None)
            try:
                text = file.read().decode("utf-8-sig")

                first_line = text.splitlines()[0] if text.splitlines() else ""
                delimiter = "\t" if first_line.count("\t") > first_line.count(",") else ","

                reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
                rows = []
                for row in reader:
                    row_data = {f: (row.get(f, "") or "") for f in CATALOG_FIELDS}
                    row_data["feed_frequency_days"] = row.get("feed_frequency_days", "") or ""
                    rows.append(row_data)
                if not rows:
                    return render_template("catalog_import.html", error="File contained no rows.", rows=None)
                missing_cols = [f for f in CATALOG_FIELDS if f not in (reader.fieldnames or [])]
                if missing_cols:
                    detected = "tab" if delimiter == "\t" else "comma"
                    found_cols = ", ".join(reader.fieldnames or [])
                    return render_template(
                        "catalog_import.html",
                        error=f"CSV is missing required columns: {', '.join(missing_cols)}. Detected delimiter: {detected}. Found columns: {found_cols}",
                        rows=None,
                    )

                output = io.StringIO()
                writer = csv.DictWriter(output, fieldnames=CATALOG_FIELDS_WITH_FREQ)
                writer.writeheader()
                for row in rows:
                    writer.writerow(row)
                normalised_csv = output.getvalue()

                return render_template("catalog_import.html", error=None, rows=rows, raw_csv=normalised_csv)
            except Exception as e:
                return render_template("catalog_import.html", error=f"Could not read file: {e}", rows=None)

        elif action == "confirm":
            raw_csv = request.form.get("raw_csv", "")
            reader = csv.DictReader(io.StringIO(raw_csv))
            conn = get_db()
            count = 0
            for row in reader:
                values = [row.get(f, "") or "" for f in CATALOG_FIELDS]
                freq = row.get("feed_frequency_days") or None
                values.append(freq)
                conn.execute(
                    """
                    INSERT INTO plant_catalog (name, npk_ratio, dosing_rules, seasonal_notes, deficiency_guide, mulch_notes, feed_frequency_days)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                        npk_ratio=excluded.npk_ratio,
                        dosing_rules=excluded.dosing_rules,
                        seasonal_notes=excluded.seasonal_notes,
                        deficiency_guide=excluded.deficiency_guide,
                        mulch_notes=excluded.mulch_notes,
                        feed_frequency_days=excluded.feed_frequency_days
                    """,
                    values,
                )
                count += 1
            conn.commit()
            conn.close()
            return render_template("catalog_import.html", error=None, rows=None, success=f"Imported {count} plant(s) successfully.")

    return render_template("catalog_import.html", error=None, rows=None)


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000)
