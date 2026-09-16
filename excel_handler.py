from pathlib import Path

import pandas as pd


TUTOR_COLUMNS = [
    "Tutor Name",
    "Seniority",
    "First Choice",
    "Second Choice",
    "Third Choice",
]

CLASS_COLUMNS = [
    "Class Name",
    "Minimum Tutors",
    "Maximum Tutors",
]


def check_required_columns(dataframe, required_columns, sheet_name):
    """Check that a worksheet contains every required column."""
    missing_columns = [
        column
        for column in required_columns
        if column not in dataframe.columns
    ]

    if missing_columns:
        raise ValueError(
            f"The {sheet_name} sheet is missing these columns: "
            f"{missing_columns}"
        )


def load_excel_file(file_path):
    """Load and validate the Tutors and Classes worksheets."""
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"Excel file not found: {file_path}")

    # Using "with" automatically closes the Excel file after reading it.
    with pd.ExcelFile(file_path) as workbook:
        required_sheets = {"Tutors", "Classes"}
        existing_sheets = set(workbook.sheet_names)
        missing_sheets = required_sheets - existing_sheets

        if missing_sheets:
            raise ValueError(
                f"The workbook is missing these sheets: "
                f"{sorted(missing_sheets)}"
            )

        tutors = pd.read_excel(
            workbook,
            sheet_name="Tutors",
        )

        classes = pd.read_excel(
            workbook,
            sheet_name="Classes",
        )

    # The workbook is closed at this point.

    tutors.columns = tutors.columns.str.strip()
    classes.columns = classes.columns.str.strip()

    check_required_columns(
        tutors,
        TUTOR_COLUMNS,
        "Tutors",
    )

    check_required_columns(
        classes,
        CLASS_COLUMNS,
        "Classes",
    )

    return tutors, classes