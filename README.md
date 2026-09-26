# Tutor-to-Class Assignment App

A web-based tool that reads an Excel file of tutors, classes, and each
tutor's top 3 preferred classes, then runs an algorithm to find the assignment 
that maximizes overall preference satisfaction.

## Requirements

- Python 3.11+
- pip

Python packages used:

- `pandas`
- `openpyxl` (lets pandas read/write `.xlsx` files)
- `flask`
- `werkzeug`

## Setup

Clone or download this repository, then from the project folder:

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
pip install pandas openpyxl flask werkzeug
```

## Excel Input Format

The uploaded workbook must contain two sheets:

**`Tutors`**

| Tutor Name | Seniority | First Choice | Second Choice | Third Choice |
|---|---|---|---|---|

`Seniority` must be one of: `Lead`, `Returning`, `New`.

**`Classes`**

| Class Name | Minimum Tutors | Maximum Tutors |
|---|---|---|

The number of rows in `Tutors` must equal the number of rows in
`Classes`, since every tutor ends up assigned to exactly one class and
every class ends up filled. A sample file that follows this format is
included at `sample_data/sample.xlsx`.

## Running the Web App

```bash
python app.py
```

Then open `http://127.0.0.1:5000/` in a browser, and upload an `.xlsx`
file matching the format above.

## Running the Algorithm Directly

To run the matching algorithm on its own, without the web interface:

```bash
python algorithm.py
```

This loads `sample_data/sample.xlsx`, runs `brute_force_match`, and
prints each tutor's assigned class, which choice number they received,
and the total preference score.

To use it in your own code:

```python
from excel_handler import load_excel_file
from algorithm import brute_force_match

tutors, classes = load_excel_file("path/to/your_file.xlsx")
results, total_score = brute_force_match(tutors, classes)

for result in results:
    print(result["Tutor Name"], "->", result["Assigned Class"])
```

## Reproducing the Test Results

Two test scripts verify the algorithm's correctness. Run them from the
project folder (same directory as `algorithm.py`, `verify.py`, and
`excel_handler.py`):

```bash
python test_algorithm.py
```

Runs `brute_force_match` against `sample_data/sample.xlsx`, then
independently re-solves the same data with a second, differently
implemented brute-force search (`verify.py`). Reports whether both
methods agree on the optimal score and produce a valid, complete
assignment. A `PASS` at the end confirms the result is genuinely
optimal, not just plausible-looking.

```bash
python test_edge_cases.py
```

Runs a set of hand-built scenarios that are unlikely to occur naturally
in a real class roster, confirming the algorithm handles each
correctly:

- Two tutors competing for the same top choice (one must be pushed to
  a lower choice, never left unassigned or double-booked).
- Mismatched tutor/class counts (should raise a clear error).
- A class nobody ever selected as a preference (should raise an error
  naming that specific class).
- A genuine scoring tie between a `Lead` and a `New` tutor (seniority
  should decide the tie, but never override the actual preference
  score).

Each check prints its own `PASS` line; an `AssertionError` points to
exactly which behavior broke.

## Project Structure

```
.
├── algorithm.py          # Core brute-force/backtracking assignment algorithm
├── app.py                # Flask web application
├── excel_handler.py      # Reads and validates the uploaded Excel workbook
├── verify.py             # Independent brute-force checker, used by test_algorithm.py
├── test_algorithm.py     # Cross-checks algorithm.py against verify.py
├── test_edge_cases.py    # Unit tests for specific edge-case behaviors
└── sample_data/
    └── sample.xlsx       # Example input file matching the required format
```