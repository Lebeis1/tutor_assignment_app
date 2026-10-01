import re
from collections import defaultdict

import pandas as pd


# Fill priority for the sheet's own "Tier" column, driven by funding rules
# stated in the sheet's instructions. Lower number = filled first, even at
# the cost of overall preference score. This mapping is a best-effort
# interpretation of the instructions text - confirm it matches how your
# office actually prioritizes these before relying on it.
TIER_FILL_PRIORITY = {
    "Tier 1": 1,
    "Tier 1 EU": 1,
    "Tier 2": 2,
    "Tier 3": 3,
    "CAT Only": 4,
}

PREFERENCE_COLUMNS = ["1st Choice", "2nd Choice", "3rd Choice"]


def _find_header_row(raw):
    """
    The sheet has an example block near the top with its own "1st
    Choice / 2nd Choice / 3rd Choice" header, followed later by the
    REAL header for the actual class data. Take the LAST matching row,
    since the real header always comes after the examples.
    """
    header_row = None

    for i, row in raw.iterrows():
        values = [str(v) for v in row.tolist()]

        if any("1st Choice" in v for v in values) and any(
            "2nd Choice" in v for v in values
        ):
            header_row = i

    if header_row is None:
        raise ValueError(
            "Could not find a header row containing '1st Choice' and "
            "'2nd Choice' in this sheet."
        )

    return header_row


def _split_candidate_names(cell):
    """
    Split a "1st Choice"-style cell into individual tutor names.

    Splits on commas OUTSIDE parentheses only, so a note like
    "Lilo (Thurs lectures only), Suzanne" splits into two names, not
    three. Strips parenthetical notes (schedule limits, "CAT", etc.)
    from each name afterward.
    """
    if pd.isna(cell):
        return []

    names = []
    depth = 0
    current = ""

    for character in str(cell):
        if character == "(":
            depth += 1
            current += character
        elif character == ")":
            depth = max(0, depth - 1)
            current += character
        elif character == "," and depth == 0:
            names.append(current)
            current = ""
        else:
            current += character

    names.append(current)

    cleaned = []

    for name in names:
        name = re.sub(r"\(.*?\)", "", name).strip()
        if name:
            cleaned.append(name)

    return cleaned


def _build_name_canonicalizer(all_raw_names):
    """
    The same tutor sometimes appears with different capitalization in
    different cells (e.g. "karen galvan" vs "Karen Galvan"). Group
    names case-insensitively and pick whichever spelling has the most
    uppercase letters as the "display" version, so names like
    "McMurray" don't get mangled by naive re-casing.
    """
    variants_by_key = defaultdict(list)

    for name in all_raw_names:
        variants_by_key[name.lower()].append(name)

    canonical_name = {}

    for key, variants in variants_by_key.items():
        best_variant = max(variants, key=lambda v: sum(c.isupper() for c in v))
        canonical_name[key] = best_variant

    def canonicalize(name):
        return canonical_name[name.lower()]

    return canonicalize


def load_real_choices(file_path, sheet_name="Choices Round 1"):
    """
    Parse the real class-oriented LRC placement sheet into a list of
    "classes needing a tutor" records, each with:

        {
            "class_id": "PSY 300 E3L",
            "tier_label": "Tier 1 EU",
            "tier_priority": 1,
            "candidates": [("Cassidy Rosenbaum", 1), ("Elizabeth Lanovaya", 1)],
        }

    Where the second element of each candidate tuple is which choice
    tier (1, 2, or 3) that tutor listed themselves under for THIS
    specific class. Classes with zero candidates across all three
    columns are left out entirely, per the "disregard it" rule.
    """
    raw = pd.read_excel(file_path, sheet_name=sheet_name, header=None)
    header_row = _find_header_row(raw)

    dataframe = pd.read_excel(file_path, sheet_name=sheet_name, header=header_row)
    dataframe = dataframe.rename(columns={dataframe.columns[0]: "Tier"})

    # Drop banner/separator rows (e.g. the "PSY EU Courses" divider),
    # which have no Subject/Section of their own.
    dataframe = dataframe.dropna(subset=["Subject", "Section"])

    # Keep Active sections only, but don't choke on a blank status.
    if "Class Status" in dataframe.columns:
        dataframe = dataframe[
            dataframe["Class Status"].isna() | (dataframe["Class Status"] == "Active")
        ]

    # First pass: collect every raw name exactly as typed, so we can
    # build one consistent canonical spelling per tutor.
    all_raw_names = []
    for column in PREFERENCE_COLUMNS:
        for cell in dataframe[column]:
            all_raw_names.extend(_split_candidate_names(cell))

    canonicalize = _build_name_canonicalizer(all_raw_names)

    classes = []
    seen_class_ids = set()

    for _, row in dataframe.iterrows():
        class_id = f"{row['Subject']} {row['Section']}".strip()

        if class_id in seen_class_ids:
            raise ValueError(
                f"Duplicate class id '{class_id}' - Subject + Section should "
                "be unique per row."
            )
        seen_class_ids.add(class_id)

        tier_label = row["Tier"]
        tier_priority = TIER_FILL_PRIORITY.get(tier_label, max(TIER_FILL_PRIORITY.values()) + 1)

        # tutor -> best (lowest/most-preferred) choice tier they listed
        # for THIS class, in case of an accidental duplicate listing.
        best_tier_for_tutor = {}

        for choice_tier, column in enumerate(PREFERENCE_COLUMNS, start=1):
            for raw_name in _split_candidate_names(row[column]):
                name = canonicalize(raw_name)
                if name not in best_tier_for_tutor or choice_tier < best_tier_for_tutor[name]:
                    best_tier_for_tutor[name] = choice_tier

        if not best_tier_for_tutor:
            continue  # no candidates at all - disregard this class

        classes.append(
            {
                "class_id": class_id,
                "tier_label": tier_label,
                "tier_priority": tier_priority,
                "candidates": sorted(best_tier_for_tutor.items(), key=lambda pair: pair[1]),
            }
        )

    return classes
