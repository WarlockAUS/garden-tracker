# Garden Tracker

A self-hosted web app for tracking garden plants, fertiliser applications, a plant catalog with feeding/planting guides, a planting & harvest calendar, and a fertiliser mix calculator. Built with Flask and SQLite, deployed as a Docker container, originally designed around managing a backyard banana clump in South East Queensland and expanded from there.

## Features

- **Dashboard** — shows each tracked plant, days since last feed, and whether it's Overdue, Due Soon, or OK based on its catalog feed frequency. Links through to the Mix Calculator pre-filled for that plant.
- **Log** — record Feed, Dolomite, Epsom Salts, Mulch, Sucker Removal, Watering, Pest Treatment, or Other actions against a specific plant, with quantity, unit, optional soil pH, and notes. Filterable by plant and action type. Entries can be edited or deleted.
- **Manage My Plants** — add the actual plants you're growing, each linked to a Plant Catalog entry. Deleting a plant also deletes its log history (with a confirmation showing exactly how many entries will be removed).
- **Plant Catalog** — a reference library of plant types, each with:
  - NPK ratio & blend notes (reference text)
  - Structured target N:P:K ratio (used by the Mix Calculator)
  - Dosing rules
  - Seasonal schedule notes
  - Deficiency guide
  - Mulching notes
  - Feed frequency (days, used by the Dashboard)
  - Planting months and harvest months (used by the Calendar)
  - Plant family (used for a lightweight crop rotation advisory note)

  Catalog entries can be added manually, edited in place, or bulk imported/updated via CSV.
- **Calendar** — shows all 12 months with which catalog plants can be planted or harvested each month. Toggle between Planting and Harvest views, and optionally filter to show only plants you actually have (via Manage My Plants).
- **Fertiliser Mix Calculator** — select a plant (pulls its target N:P:K ratio from the catalog), select which ingredient supplies each of N, P, and K from your saved Ingredients list (percentages taken straight off the product packet), set a batch size, and it calculates the exact weight of each ingredient needed, plus the resulting blend's actual N/P/K percentages and secondary nutrient content (Ca, Mg, S) as an informational bonus.
- **Ingredients** — a reusable list of fertiliser products and their packet percentages (N, P, K, Ca, Mg, S), used by the Mix Calculator.

## Tech stack

- **Backend:** Python 3, Flask
- **Database:** SQLite (file-based, stored in a mounted volume)
- **Frontend:** Server-rendered HTML templates (Jinja2), minimal vanilla JS for calendar toggles
- **Deployment:** Docker image built and published automatically via GitHub Actions to GitHub Container Registry (ghcr.io), run as a Custom App on TrueNAS Community Edition

## Repository structureapp.py — all routes, database logic, and the mix calculation
requirements.txt — Python dependencies (Flask)
Dockerfile — container build instructions
templates/ — HTML templates (Jinja2)
.github/workflows/docker-publish.yml — CI pipeline: builds and publishes the Docker image on every push to main


## How updates are built and deployed

Every push to `main` triggers a GitHub Actions workflow that:
1. Builds a Docker image from the current code
2. Publishes it to `ghcr.io/warlockaus/garden-tracker` tagged both `latest` and an incrementing version tag (`v1.X`, based on the GitHub Actions run number)

On TrueNAS, the app is deployed as a **Custom App** with:
- Image: `ghcr.io/warlockaus/garden-tracker:latest`
- Pull Policy: **Always** (forces a fresh pull of the `latest` tag on every start, since TrueNAS otherwise has no way of detecting that the content behind a floating tag has changed)
- A Host Path storage mount pointing to a dedicated dataset (e.g. `garden-tracker-data`), mapped to `/app/data` inside the container — this is where the SQLite database (`garden.db`) lives, so it persists across container restarts/updates and is covered by TrueNAS's snapshot schedule

**To deploy a change:**
1. Edit files directly on GitHub (or push via git)
2. Check the **Actions** tab for a green tick confirming the build succeeded
3. On TrueNAS, stop and start the `garden-tracker` app (or edit and re-save it) to force a fresh pull

**Note:** TrueNAS's own "Up to date" indicator in the Apps list does **not** reflect whether a new image is available for this app, it only reflects whether the app's own configuration has changed. Since this is a Custom App (not installed from the official Apps catalog), TrueNAS has no visibility into the container registry's contents. The only reliable way to know an update is ready is checking the GitHub Actions tab after a commit.

**Rolling back:** if an update causes a problem, note the previous working version tag (visible in the Actions run history or the repository's Packages page) and change the Tag field in the TrueNAS Custom App config from `latest` to that specific version (e.g. `v1.42`), then save. This pins the app to that exact build regardless of what `latest` currently points to.

## Database notes

- SQLite database file: `/app/data/garden.db` (inside the container; mapped to a persistent dataset on the host)
- Tables: `plant_catalog`, `plants`, `log_entries`, `fertiliser_ingredients`
- Schema changes are applied automatically on startup via `init_db()`, which checks for missing columns/tables and adds them without destroying existing data

## CSV import format (Plant Catalog)

Required columns (exact header names): `name, npk_ratio, dosing_rules, seasonal_notes, deficiency_guide, mulch_notes`

Optional columns, also supported if included: `feed_frequency_days, npk_n, npk_p, npk_k, plant_months, harvest_months, plant_family`

- `plant_months` / `harvest_months` — comma-separated month numbers, e.g. `3,4,5`
- Import matches on `name`; existing entries are updated in place, new names are added
- Delimiter (comma or tab) is auto-detected

**⚠️ Important:** Never open a CSV file in Excel or Google Sheets at any point before importing (including just to check it), even without saving. Spreadsheet programs will silently reinterpret comma-separated digit strings (like month lists) as numbers, corrupting the data (e.g. `4,5` becomes `45`, or a long list becomes scientific notation). Create and check CSV files using a plain text editor only (e.g. Notepad — use "Open with" → Notepad specifically, never double-click).

## Known limitations / things deliberately not built

- No user accounts/authentication — intended for personal use on a home network only
- No climate zone support — all seasonal/planting data is calibrated specifically for South East Queensland's subtropical climate; using this catalog data elsewhere would need different planting/harvest months
- No bed/rotation tracking — plant family is shown as an informational note only, not enforced
- No automatic update notifications — see "How updates are built and deployed" above
- No photo attachments on log entries
