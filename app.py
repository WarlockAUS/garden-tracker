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
CATALOG_EXTRA_FIELDS = ["feed_frequency_days", "npk_n", "npk_p", "npk_k", "plant_months", "harvest_months", "plant_family"]
CATALOG_FIELDS_WITH_FREQ = CATALOG_FIELDS + CATALOG_EXTRA_FIELDS

INGREDIENT_FIELDS = ["name", "n_pct", "p_pct", "k_pct", "ca_pct", "mg_pct", "s_pct"]

FAMILY_NOTES = {
    "Nightshade": "Avoid planting in the exact same spot for 2-3 seasons in a row where possible, to reduce soil-borne disease risk (e.g. fusarium, verticillium wilt).",
    "Legume": "Fixes nitrogen in the soil; a useful plant to follow heavy feeders with, rather than something to avoid repeating.",
    "Brassica": "Prone to club root build-up in soil if grown in the same spot repeatedly; vary location where practical.",
    "Cucurbit": "Prone to soil-borne mildew and wilt build-up; vary location where practical.",
    "Allium": "Generally low rotation risk, but avoid directly following another allium crop in the same spot.",
    "Root Vegetable": "Low rotation risk; avoid excess fresh manure right before planting as it can cause forking of roots.",
    "Herb": "Generally flexible, low rotation risk.",
    "Fruit Tree": "Long-term perennial; rotation doesn't apply once established.",
}

BANANA_CATALOG_ENTRY = {
    "name": "Banana",
    "npk_ratio": "Target ratio approx. 3 : 1 : 6 (N : P2O5 : K2O).\nMineral blend: 365g Sulphate of Ammonia (21% N) : 270g Superphosphate (9.1% P2O5) : 365g Sulphate of Potash (41.5% K2O) per 1kg batch.\nResulting analysis: ~7.67% N, 2.46% P2O5, 15.15% K2O.",
    "dosing_rules": "Start at 50g of blend per clump per application.\nFrequency: every 4-6 weeks while actively growing.\nSpread thinly across the wider root zone, not a tight ring.\nApply to moist soil, water in gently afterwards.\nReduce or pause over winter if growth visibly slows.\nHold at 50g for at least a full season before increasing.",
    "seasonal_notes": "Spring-Summer: feed every 4-6 weeks, 50g.\nAutumn: taper to 30-50g.\nWinter: pause feeding unless still actively growing. Soil test before applying dolomite.\nSpring: resume full feeding 2-3 weeks clear of any winter dolomite.",
    "deficiency_guide": "Yellowing between veins, veins stay green: Magnesium deficiency.\nGeneral pale yellowing, slow growth: Nitrogen deficiency.\nDark green leaves, weak stems, poor bunch fill: Potassium deficiency.\nBrown scorched leaf margins, wilting: Over-fertilising.\nPurplish/reddish leaf tinge: Phosphorus deficiency.",
    "mulch_notes": "Depth: approx 10cm organic mulch. Keep clear of stems.\nSequence: pull mulch back, apply fertiliser, water in, replace mulch.\nTop up every 2-3 months.\nSucker thinning: keep main stem plus 1-2 followers, remove extras while small.",
    "feed_frequency_days": 42,
    "npk_n": 3,
    "npk_p": 1,
    "npk_k": 6,
    "plant_months": "9,10,11",
    "harvest_months": "1,2,3,4,5,6,7,8,9,10,11,12",
    "plant_family": "Fruit Tree",
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

    conn.execute("""
        CREATE TABLE IF NOT EXISTS fertiliser_ingredients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            n_pct REAL,
            p_pct REAL,
            k_pct REAL,
            ca_pct REAL,
            mg_pct REAL,
            s_pct REAL
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
    if "npk_n" not in catalog_columns:
        conn.execute("ALTER TABLE plant_catalog ADD COLUMN npk_n REAL")
    if "npk_p" not in catalog_columns:
        conn.execute("ALTER TABLE plant_catalog ADD COLUMN npk_p REAL")
    if "npk_k" not in catalog_columns:
        conn.execute("ALTER TABLE plant_catalog ADD COLUMN npk_k REAL")
    if "plant_months" not in catalog_columns:
        conn.execute("ALTER TABLE plant_catalog ADD COLUMN plant_months TEXT")
    if "harvest_months" not in catalog_columns:
        conn.execute("ALTER TABLE plant_catalog ADD COLUMN harvest_months TEXT")
    if "plant_family" not in catalog_columns:
        conn.execute("ALTER TABLE plant_catalog ADD COLUMN plant_family TEXT")

    existing = conn.execute(
        "SELECT id FROM plant_catalog WHERE name = ?", (BANANA_CATALOG_ENTRY["name"],)
    ).fetchone()
    if not existing:
        conn.execute(
            """
            INSERT INTO plant_catalog
            (name, npk_ratio, dosing_rules, seasonal_notes, deficiency_guide, mulch_notes,
             feed_frequency_days, npk_n, npk_p, npk_k, plant_months, harvest_months, plant_family)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
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
        conn.execute(
            "UPDATE plant_catalog SET npk_n=?, npk_p=?, npk_k=? WHERE id=? AND npk_n IS NULL",
            (BANANA_CATALOG_ENTRY["npk_n"], BANANA_CATALOG_ENTRY["npk_p"], BANANA_CATALOG_ENTRY["npk_k"], banana_catalog_id),
        )
        conn.execute(
            "UPDATE plant_catalog SET plant_months=?, harvest_months=? WHERE id=? AND plant_months IS NULL",
            (BANANA_CATALOG_ENTRY["plant_months"], BANANA_CATALOG_ENTRY["harvest_months"], banana_catalog_id),
        )
        conn.execute(
            "UPDATE plant_catalog SET plant_family=? WHERE id=? AND plant_family IS NULL",
            (BANANA_CATALOG_ENTRY["plant_family"], banana_catalog_id),
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

    ing_count = conn.execute("SELECT COUNT(*) FROM fertiliser_ingredients").fetchone()[0]
    if ing_count == 0:
        conn.executemany(
            "INSERT INTO fertiliser_ingredients (name, n_pct, p_pct, k_pct, ca_pct, mg_pct, s_pct) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("Sulphate of Ammonia", 21, 0, 0, 0, 0, 24),
                ("Superphosphate", 0, 9.1, 0, 0, 0, 0),
                ("Sulphate of Potash", 0, 0, 41.5, 0, 0, 17),
            ],
        )

    conn.commit()
    conn.close()


def get_plants():
    conn = get_db()
    plants = conn.execute("""
        SELECT plants.*, plant_catalog.name AS catalog_name,
               (SELECT COUNT(*) FROM log_entries WHERE log_entries.plant_id = plants.id) AS log_count
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


def get_ingredients():
    conn = get_db()
    ingredients = conn.execute("SELECT * FROM fertiliser_ingredients ORDER BY name").fetchall()
    conn.close()
    return ingredients


def get_dashboard_data():
    conn = get_db()
    plants = conn.execute("""
        SELECT plants.id, plants.name, plant_catalog.id AS catalog_id, plant_catalog.name AS catalog_name,
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
            "catalog_id": p["catalog_id"],
            "catalog_name": p["catalog_name"],
            "frequency_days": p["feed_frequency_days"],
            "last_feed_date": last_feed_date,
            "days_since": days_since,
            "status": status,
        })

    conn.close()
    return results

def get_calendar_data():
    conn = get_db()
    catalog = conn.execute("SELECT * FROM plant_catalog ORDER BY name").fetchall()
    owned_ids = set(
        row["catalog_id"] for row in conn.execute(
            "SELECT DISTINCT catalog_id FROM plants WHERE catalog_id IS NOT NULL"
        )
    )
    conn.close()

    months = {m: {"planting": [], "harvesting": []} for m in range(1, 13)}

    for entry in catalog:
        plant_list = [int(x) for x in (entry["plant_months"] or "").split(",") if x.strip().isdigit()]
        harvest_list = [int(x) for x in (entry["harvest_months"] or "").split(",") if x.strip().isdigit()]

        family = entry["plant_family"] or ""
        note = FAMILY_NOTES.get(family, "")
        is_mine = entry["id"] in owned_ids

        info = {"name": entry["name"], "family": family, "note": note, "mine": is_mine}

        for m in plant_list:
            if m in months:
                months[m]["planting"].append(info)
        for m in harvest_list:
            if m in months:
                months[m]["harvesting"].append(info)

    return months


def calculate_mix(target_n, target_p, target_k, batch_size, ing_n, ing_p, ing_k):
    try:
        a = (ing_n["n_pct"] or 0) / 100.0
        b = (ing_p["p_pct"] or 0) / 100.0
        c = (ing_k["k_pct"] or 0) / 100.0

        if a <= 0 or b <= 0 or c <= 0:
            return None, "One of the selected ingredients has 0% listed for its intended nutrient role. Choose a different ingredient for that role, or check the percentage entered."

        terms = (target_n / a) + (target_p / b) + (target_k / c)
        if terms <= 0:
            return None, "Target ratio must contain positive values for N, P and K."

        k_scalar = batch_size / terms
        w_n = k_scalar * target_n / a
        w_p = k_scalar * target_p / b
        w_k = k_scalar * target_k / c
        total = w_n + w_p + w_k

        result_n = w_n * a
        result_p = w_p * b
        result_k = w_k * c

        secondary = {}
        for field, label in [("ca_pct", "Calcium"), ("mg_pct", "Magnesium"), ("s_pct", "Sulfur")]:
            total_secondary = 0.0
            for ing, w in [(ing_n, w_n), (ing_p, w_p), (ing_k, w_k)]:
                pct = ing[field] or 0
                total_secondary += w * (pct / 100.0)
            secondary[label] = round(total_secondary, 1)

        return {
            "w_n": round(w_n, 1),
            "w_p": round(w_p, 1),
            "w_k": round(w_k, 1),
            "total": round(total, 1),
            "result_n_pct": round((result_n / total * 100), 2) if total else 0,
            "result_p_pct": round((result_p / total * 100), 2) if total else 0,
            "result_k_pct": round((result_k / total * 100), 2) if total else 0,
            "secondary": secondary,
        }, None
    except ZeroDivisionError:
        return None, "Calculation error, check the ingredient percentages entered."


@app.route("/")
def dashboard():
    data = get_dashboard_data()
    return render_template("dashboard.html", data=data)


@app.route("/calendar")
def calendar_view():
    month_names = ["January", "February", "March", "April", "May", "June",
                   "July", "August", "September", "October", "November", "December"]
    current_month = date.today().month
    data = get_calendar_data()
    return render_template(
        "calendar.html", data=data, month_names=month_names, current_month=current_month
    )


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

    delete_error = request.args.get("delete_error")
    return render_template("plants.html", plants=get_plants(), catalog=get_catalog(), delete_error=delete_error)


@app.route("/plants/delete/<int:plant_id>", methods=["POST"])
def delete_plant(plant_id):
    conn = get_db()
    conn.execute("DELETE FROM log_entries WHERE plant_id = ?", (plant_id,))
    conn.execute("DELETE FROM plants WHERE id = ?", (plant_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("manage_plants"))


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
        values = [request.form.get(f, "") for f in CATALOG_FIELDS[1:]]
        freq = request.form.get("feed_frequency_days") or None
        npk_n = request.form.get("npk_n") or None
        npk_p = request.form.get("npk_p") or None
        npk_k = request.form.get("npk_k") or None
        plant_months = request.form.get("plant_months") or None
        harvest_months = request.form.get("harvest_months") or None
        plant_family = request.form.get("plant_family") or None

        conn.execute(
            """
            UPDATE plant_catalog
            SET npk_ratio=?, dosing_rules=?, seasonal_notes=?, deficiency_guide=?, mulch_notes=?,
                feed_frequency_days=?, npk_n=?, npk_p=?, npk_k=?, plant_months=?, harvest_months=?, plant_family=?
            WHERE id=?
            """,
            (*values, freq, npk_n, npk_p, npk_k, plant_months, harvest_months, plant_family, catalog_id),
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
        for f in CATALOG_EXTRA_FIELDS:
            values.append(request.form.get(f) or None)
        conn = get_db()
        conn.execute(
            """
            INSERT INTO plant_catalog
            (name, npk_ratio, dosing_rules, seasonal_notes, deficiency_guide, mulch_notes,
             feed_frequency_days, npk_n, npk_p, npk_k, plant_months, harvest_months, plant_family)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                npk_ratio=excluded.npk_ratio,
                dosing_rules=excluded.dosing_rules,
                seasonal_notes=excluded.seasonal_notes,
                deficiency_guide=excluded.deficiency_guide,
                mulch_notes=excluded.mulch_notes,
                feed_frequency_days=excluded.feed_frequency_days,
                npk_n=excluded.npk_n,
                npk_p=excluded.npk_p,
                npk_k=excluded.npk_k,
                plant_months=excluded.plant_months,
                harvest_months=excluded.harvest_months,
                plant_family=excluded.plant_family
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
                    for extra in CATALOG_EXTRA_FIELDS:
                        row_data[extra] = row.get(extra, "") or ""
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
                for extra in CATALOG_EXTRA_FIELDS:
                    values.append(row.get(extra) or None)
                conn.execute(
                    """
                    INSERT INTO plant_catalog
                    (name, npk_ratio, dosing_rules, seasonal_notes, deficiency_guide, mulch_notes,
                     feed_frequency_days, npk_n, npk_p, npk_k, plant_months, harvest_months, plant_family)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                        npk_ratio=excluded.npk_ratio,
                        dosing_rules=excluded.dosing_rules,
                        seasonal_notes=excluded.seasonal_notes,
                        deficiency_guide=excluded.deficiency_guide,
                        mulch_notes=excluded.mulch_notes,
                        feed_frequency_days=excluded.feed_frequency_days,
                        npk_n=excluded.npk_n,
                        npk_p=excluded.npk_p,
                        npk_k=excluded.npk_k,
                        plant_months=excluded.plant_months,
                        harvest_months=excluded.harvest_months,
                        plant_family=excluded.plant_family
                    """,
                    values,
                )
                count += 1
            conn.commit()
            conn.close()
            return render_template("catalog_import.html", error=None, rows=None, success=f"Imported {count} plant(s) successfully.")

    return render_template("catalog_import.html", error=None, rows=None)


@app.route("/ingredients", methods=["GET", "POST"])
def manage_ingredients():
    if request.method == "POST":
        values = [request.form.get(f) for f in INGREDIENT_FIELDS]
        values = [values[0]] + [v or 0 for v in values[1:]]
        conn = get_db()
        conn.execute(
            """
            INSERT INTO fertiliser_ingredients (name, n_pct, p_pct, k_pct, ca_pct, mg_pct, s_pct)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                n_pct=excluded.n_pct, p_pct=excluded.p_pct, k_pct=excluded.k_pct,
                ca_pct=excluded.ca_pct, mg_pct=excluded.mg_pct, s_pct=excluded.s_pct
            """,
            values,
        )
        conn.commit()
        conn.close()
        return redirect(url_for("manage_ingredients"))

    return render_template("ingredients.html", ingredients=get_ingredients())


@app.route("/ingredients/delete/<int:ingredient_id>", methods=["POST"])
def delete_ingredient(ingredient_id):
    conn = get_db()
    conn.execute("DELETE FROM fertiliser_ingredients WHERE id = ?", (ingredient_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("manage_ingredients"))


@app.route("/mix", methods=["GET", "POST"])
def mix_calculator():
    conn = get_db()
    plants = conn.execute("""
        SELECT plants.id, plants.name, plant_catalog.name AS catalog_name,
               plant_catalog.npk_n, plant_catalog.npk_p, plant_catalog.npk_k
        FROM plants LEFT JOIN plant_catalog ON plants.catalog_id = plant_catalog.id
        ORDER BY plants.name
    """).fetchall()
    ingredients = conn.execute("SELECT * FROM fertiliser_ingredients ORDER BY name").fetchall()
    conn.close()

    result = None
    error = None
    selected_plant_id = request.args.get("plant_id")
    selected_n_id = None
    selected_p_id = None
    selected_k_id = None
    batch_size = 1000

    if request.method == "POST":
        selected_plant_id = request.form.get("plant_id")
        selected_n_id = request.form.get("ingredient_n")
        selected_p_id = request.form.get("ingredient_p")
        selected_k_id = request.form.get("ingredient_k")
        batch_size = float(request.form.get("batch_size") or 1000)

        plant = next((p for p in plants if str(p["id"]) == selected_plant_id), None)
        ing_n = next((i for i in ingredients if str(i["id"]) == selected_n_id), None)
        ing_p = next((i for i in ingredients if str(i["id"]) == selected_p_id), None)
        ing_k = next((i for i in ingredients if str(i["id"]) == selected_k_id), None)

        if not plant or plant["npk_n"] is None or plant["npk_p"] is None or plant["npk_k"] is None:
            error = "Selected plant has no target NPK ratio set in its catalog entry. Edit the catalog entry to add one."
        elif not ing_n or not ing_p or not ing_k:
            error = "Please select an ingredient for each of the N, P and K roles."
        else:
            result, error = calculate_mix(
                plant["npk_n"], plant["npk_p"], plant["npk_k"], batch_size, ing_n, ing_p, ing_k
            )

    return render_template(
        "mix.html",
        plants=plants,
        ingredients=ingredients,
        result=result,
        error=error,
        selected_plant_id=selected_plant_id,
        selected_n_id=selected_n_id,
        selected_p_id=selected_p_id,
        selected_k_id=selected_k_id,
        batch_size=batch_size,
    )


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000)
