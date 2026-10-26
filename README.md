# Tutor Placement Draft Tool

A web app for the Learning Resource Center (LRC). Staff upload the placement
workbook, where tutors list their top three class choices, and the app produces
a **draft** assignment of tutors to classes. The draft is a starting point to
review and adjust, not a final answer: staff can drag and drop tutors to change
it, then download the result as an Excel file.

## Requirements

- Python 3.11+
- pip

Python packages used:

- `flask` (web app)
- `pandas` and `openpyxl` (reading and writing `.xlsx` files)
- `scipy` (the matching solver)

## Setup

From the project folder:

```bash
python -m venv venv
```

Activate it:

```bash
# Windows (PowerShell)
venv\Scripts\Activate.ps1

# macOS / Linux
source venv/bin/activate
```

Install dependencies:

```bash
pip install flask pandas openpyxl scipy
```

## Running the Web App

```bash
python app.py
```

Open `http://127.0.0.1:5000/` in a browser, choose the `.xlsx` workbook, and
upload it. The results page opens with the draft.

Flask prints "This is a development server" when it starts. That is normal for
local use. If other people will use the tool on a shared machine or server, run
it under a production server instead and turn off debug mode (see "Running it
for real" below).

### What happens to uploaded files

Each upload is saved briefly under a random name in the `uploads` folder, read,
and deleted straight after the run, even if the run fails. As a safety net, any
leftover file older than 5 minutes is removed when the app starts and on each
upload. Nothing is kept between runs. Uploads are limited to 10 MB and `.xlsx`
files only.

## What the Results Page Shows

- **By class:** every class with its assigned tutor, which choice (1st, 2nd,
  3rd) that was for the tutor, warnings, and any other equally good options.
  Filter by class or tutor name, or tick "Show only open classes".
- **By tutor:** a read-only summary of each tutor's classes and load, plus the
  tutors who have no class yet.
- **Needs attention:** open classes and warnings in one place.
- Notices at the top for things worth checking in the file (for example a Link
  Group label used only once).

### Editing the draft

- Drag a tutor's name onto another class to move them, or drop it in the tray at
  the bottom to set it aside. You can also click a name in the tray, then click a
  class.
- Dropping on a class that already has a tutor replaces them, and the replaced
  tutor goes to the tray.
- **Two tutors on one class:** while you drag, a dashed "+ add a 2nd tutor" spot
  appears next to the current tutor on classes that have one. Drop the name on
  that spot to add a second tutor instead of replacing. With a name selected from
  the tray, click that spot instead. On a class that already has two tutors,
  drop onto the name you want to replace. If you remove the first tutor, the
  second one becomes the main tutor.
- A lock icon (🔒) next to a name means the sheet locked that tutor to that
  class. Moving a locked tutor away shows a warning, but is allowed.
- Any move is allowed. Risky moves (for example the tutor didn't list that
  class, or it goes over their Max Classes) show a warning instead of being
  blocked.
- Linked classes (see Link Group below) move one row at a time, with a warning if
  that separates them.
- Undo and Reset buttons are available, and the page warns before you leave with
  unsaved changes.
- **Export to Excel** downloads exactly what is on screen, including your edits.
  The Assignments sheet has the course (for example `MATH 300`) and its section
  (for example `2`) in separate columns, plus columns for a second tutor. The file also has a By Tutor sheet and a Summary sheet (with
  tray names and skipped canceled classes).

## Excel Input Format

The app reads the real LRC placement workbook.

**`Choices Round 1` sheet** (required). One row per class. The app finds the
header row by looking for the last row that contains both "1st Choice" and
"2nd Choice". The columns it uses:

| Column | Meaning |
|---|---|
| First column | Tier of the class (see below) |
| `1st Choice`, `2nd Choice`, `3rd Choice` | Tutor names. Several names may share one cell, separated by commas |
| `Subject`, `Section` | Together identify the class, e.g. `PSY 300` + `E3L`. The export keeps them in separate columns |
| `Link Group` (optional) | Label that ties a lecture and its lab(s) together |

Other columns (day, time, instructor, and so on) are ignored.

**`Tutors` sheet** (optional). One row per tutor:

| Tutor Name | Seniority | Max Classes |
|---|---|---|

- `Seniority` must be `Lead`, `Returning` or `New`. It is only used to break ties.
- `Max Classes` is a whole number of 1 or more. Blank means the default of 2.
- If a name on this sheet matches nobody on the choices sheet, or a value is
  invalid, the app stops with a message that says which one.

### Tiers

A class's tier decides how urgently it should be filled, from highest to lowest:
Tier 1, Tier 1 EU, Tier 2, Tier 3, then CAT Only.

### Notes tutors write next to their names

- Writing exactly `(CAT)` next to a name (any capitalization) marks that tutor as
  Canvas-Attached only for that class. The app avoids placing them in a class
  that isn't in the CAT Only tier when another tutor can take it.
- Writing exactly `(locked)` next to a name (any capitalization) fixes that tutor
  to that class, whoever else listed it. See "Locked tutors" below.
- Any other note in parentheses, such as `(possibly locked)` or `(CAT like last
  sem!)`, is ignored: it does not change the draft and is not shown on the
  results page.
- Write names without extra text outside the parentheses. A name like `Ann Lee
  CAT` is read as a different tutor.

### Locked tutors

A tutor marked `(locked)` is placed in that class exactly as the sheet says, even
if another tutor ranked it higher.

- The locked class is taken out of the matching. It counts as one of the tutor's
  Max Classes, and a locked tutor no longer counts as someone still waiting for a
  first class.
- If two tutors are locked to the same class, both are placed there (a class
  holds two tutors). A notice explains this.
- If a tutor is locked to more classes than their Max Classes, all locks are kept
  and a notice says so.
- Link Groups: a locked section stays with its tutor and the remaining sections
  of that group are matched on their own, so a tutor who also takes another
  section of the group uses one more of their Max Classes.
- On the results page a locked tutor shows a lock icon, and moving them away
  shows a warning.

### Canceled classes

A class whose Subject or Section cell is struck through in Excel is treated as
canceled. It is not filled, not counted as open, and not shown as a class. The
results page and the Summary sheet say how many were skipped.

### Link Group (lectures and labs)

Give classes that belong together the same label in the `Link Group` column, for
example `PSY 300 - A` on a lecture and its lab(s).

- A linked group counts as **one class** toward a tutor's Max Classes, but each
  section is still shown as its own row.
- A tutor can take the whole group only if they listed **every** section in it.
- If that is not possible, or it would leave classes unfilled or tutors without
  a class, the group is split and a notice explains why. A lab can then go to a
  different tutor.
- Sections in a group that have **no tutor names** at all are assumed unfillable.
  They are shown as "also linked, not placed" and are never filled automatically.

## How the Draft Is Chosen

The app finds the best assignment under these rules, in this order of
importance:

0. Locked tutors (`(locked)`) are placed first, as the sheet says.
1. Only tutors' listed choices are used. Classes with no tutor names stay open.
2. Higher tiers are filled first, and a higher tier always wins over a lower one.
3. As many tutors as possible get at least one class.
4. Placements marked `(CAT)` in non-CAT Only classes are avoided.
5. Higher preference scores are better (1st choice = 3, 2nd = 2, 3rd = 1).
6. Seniority (Lead, then Returning, then New) only breaks remaining ties.

No tutor gets more than their Max Classes. The matching is solved exactly with
SciPy's `linear_sum_assignment`, so the draft is the true optimum under these
rules, not an approximation.

"Other equally good options" appear on a class only when another tutor could
take it without making the assignment any worse on every rule above, including
seniority. With seniority filled in, such ties are rare.

## Running the Algorithm Directly

To run the matching without the web interface:

```bash
python algorithm.py path/to/workbook.xlsx
```

This prints the assignment for each class. In your own code:

```python
from placement_service import run_placement

result = run_placement("path/to/workbook.xlsx")
for row in result["rows"]:
    print(row["class"], "->", row["tutor"])
```

## Running Tests

Run from the project folder:

```bash
python test_link_groups.py
python test_export.py
python test_canceled.py
python test_locked.py
```

- `test_link_groups.py` checks the fast solver against a slow brute-force search
  on 150 random small problems (they must agree), checks the Link Group
  scenarios and the group-splitting search, and checks that unstaffed linked
  classes are shown correctly.
- `test_export.py` checks the Excel export and that malformed export requests
  are rejected.
- `test_canceled.py` checks that struck-through classes are skipped everywhere.
- `test_locked.py` checks `(locked)` handling: a lock beats other votes, uses up
  Max Classes, two locks share a class, and the solver still matches the
  brute-force search when some tutors already hold a locked class.

Each check prints a `PASS` line. An `AssertionError` points to the behavior that
broke. The brute-force search is used only in these tests. The app never runs it.

## Running it for real

For anything beyond your own computer, do not use `python app.py`. In `app.py`,
change the last line to `app.run()` (debug mode can expose your code), or use a
production server:

```bash
# Windows
pip install waitress
waitress-serve --port 5000 app:app

# macOS / Linux
pip install gunicorn
gunicorn app:app
```

The workbook contains tutor names and choices, so restrict access to people who
should see it.

## Project Structure

```
.
├── app.py                 # Flask web app: upload, results and export routes
├── placement_service.py   # Runs one placement and builds the data the page shows
├── algorithm.py           # Matching solver (exact), alternatives, CAT rules
├── link_groups.py         # Link Group handling: merging, splitting, expanding
├── excel_handler.py       # Reads the workbook: choices, tutors, canceled classes
├── exporter.py            # Builds the downloadable Excel file
├── templates/
│   ├── base.html
│   ├── index.html         # Upload page
│   └── results.html       # Results page with drag-and-drop editing
├── test_link_groups.py    # Solver vs brute force, Link Group tests
├── test_export.py         # Export tests
├── test_canceled.py       # Canceled-class tests
├── test_locked.py         # Locked-tutor tests
└── uploads/               # Temporary storage for uploads (cleaned automatically)
```