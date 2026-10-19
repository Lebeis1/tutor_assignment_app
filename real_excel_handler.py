import re
import warnings
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


def _split_candidate_entries(cell):
    """
    Split a "1st Choice"-style cell into (tutor_name, is_cat) pairs.

    Splits on commas OUTSIDE parentheses only, so a note like
    "Lilo (Thurs lectures only), Suzanne" splits into two names, not
    three. Parenthetical notes are removed from the name afterward.

    is_cat is True when one of the name's parenthetical notes is exactly
    "(CAT)" (case-insensitive) - the tutor can only be Canvas Attached
    to that class. Only that exact standard is recognised: variants
    such as "(CAT only)" or "(maybe CAT)" are NOT treated as CAT, so
    tutors need to be told to write exactly "(CAT)".
    """
    if pd.isna(cell):
        return []

    pieces = []
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
            pieces.append(current)
            current = ""
        else:
            current += character

    pieces.append(current)

    entries = []

    for piece in pieces:
        notes = re.findall(r"\(([^)]*)\)", piece)
        is_cat = any(note.strip().lower() == "cat" for note in notes)
        name = re.sub(r"\(.*?\)", "", piece).strip()
        if name:
            entries.append((name, is_cat))

    return entries


def _split_candidate_names(cell):
    """Just the tutor names from a choice cell (see _split_candidate_entries)."""
    return [name for name, _ in _split_candidate_entries(cell)]


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


def _is_real_instructor(name):
    """Placeholder instructor names don't identify a real person, so
    they should never be used to infer that two sections are related."""
    placeholders = {"tba", "staff", "tbd", "instructor tba", "unassigned", ""}
    return str(name).strip().lower() not in placeholders


def _is_eu_section(section):
    """An 'E'-prefixed section code (e.g. 'E1', 'E2 LAB') marks a
    separate EU-funded track per the sheet's own instructions - two
    sections should never be considered related unless they agree on
    this, even if taught by the same instructor (the same person can
    teach both a regular offering and an unrelated EU offering)."""
    return bool(re.match(r"^E\d", str(section).strip()))


def find_related_sections(file_path, sheet_name="Choices Round 1"):
    """
    Group class_ids that likely belong to the same course offering
    (a lecture and its lab section(s)), re-derived fresh from whatever
    sheet is passed in - this does NOT hardcode any specific course
    names, so it keeps working correctly as the actual course list
    changes every semester.

    Grouping key: same Subject + Course Description + Instructor, with
    placeholder instructors ("TBA", "Staff", etc.) excluded entirely
    (they don't reliably identify a real person) and EU-prefixed
    sections ("E1", "E2 LAB") kept separate from non-EU sections even
    under the same instructor, since the same person can teach two
    unrelated offerings.

    This is a heuristic, not a guarantee - the sheet alone doesn't
    always disambiguate perfectly (e.g. one instructor genuinely
    teaching two different lecture sections of the same course back to
    back could still look like one group). It's intended ONLY as a
    low-stakes tie-breaking hint between tutors who are already
    equally-optimal candidates, never as a hard rule.

    Returns a dict: class_id -> group_id (a string), where class_ids
    sharing the same group_id are the suggested lecture+lab family.
    class_ids with no related sections get their own unique group_id.
    """
    raw = pd.read_excel(file_path, sheet_name=sheet_name, header=None)
    header_row = _find_header_row(raw)

    dataframe = pd.read_excel(file_path, sheet_name=sheet_name, header=header_row)
    dataframe = dataframe.rename(columns={dataframe.columns[0]: "Tier"})
    dataframe = dataframe.dropna(subset=["Subject", "Section"])

    if "Class Status" in dataframe.columns:
        dataframe = dataframe[
            dataframe["Class Status"].isna() | (dataframe["Class Status"] == "Active")
        ]

    dataframe["_class_id"] = dataframe["Subject"].astype(str) + " " + dataframe["Section"].astype(str)
    dataframe["_is_eu"] = dataframe["Section"].apply(_is_eu_section)

    group_by_class_id = {}

    groupable = dataframe[dataframe["Instructor"].apply(_is_real_instructor)]
    for (subject, description, instructor, is_eu), rows in groupable.groupby(
        ["Subject", "Course Description", "Instructor", "_is_eu"]
    ):
        group_id = f"{subject}|{description}|{instructor}|{'EU' if is_eu else 'regular'}"
        for class_id in rows["_class_id"]:
            group_by_class_id[class_id] = group_id

    # Anything not grouped (placeholder instructor, or simply the only
    # section of its kind) gets its own standalone group of one.
    for class_id in dataframe["_class_id"]:
        if class_id not in group_by_class_id:
            group_by_class_id[class_id] = f"standalone|{class_id}"

    return group_by_class_id


def load_tutor_info(file_path, sheet_name="Tutors", known_tutor_names=None):
    """
    Read the per-tutor "Tutors" sheet: one row per tutor, with columns
    "Tutor Name", "Seniority" (Lead / Returning / New) and "Max Classes"
    (a whole number of 1 or more).

    Returns (capacities, seniority):
        capacities: {tutor_name: max_classes}
        seniority:  {tutor_name: "Lead" | "Returning" | "New"}

    Blank cells are skipped, so a tutor with no Max Classes simply gets
    the default capacity and a tutor with no Seniority simply gets no
    seniority tie-break. If the workbook has no sheet with this name,
    both dicts come back empty and everything runs on defaults.

    known_tutor_names: pass the names that appear in the Choices sheet
    (see tutor_names_from_classes). Names on the Tutors sheet are then
    matched to them case-insensitively, and any name that matches no
    one raises a warning - that is almost always a typo, and without
    the warning its row would be silently ignored.

    Raises ValueError for a Seniority that isn't one of the three
    allowed values, or a Max Classes that isn't a whole number >= 1,
    naming the tutor so the cell is easy to find.
    """
    with pd.ExcelFile(file_path) as workbook:
        if sheet_name not in workbook.sheet_names:
            return {}, {}

    dataframe = pd.read_excel(file_path, sheet_name=sheet_name)
    dataframe.columns = dataframe.columns.str.strip()

    missing = [c for c in ("Tutor Name", "Seniority", "Max Classes") if c not in dataframe.columns]
    if missing:
        raise ValueError(
            f"The '{sheet_name}' sheet is missing these columns: {missing}"
        )

    allowed_seniority = {"lead": "Lead", "returning": "Returning", "new": "New"}
    name_by_lowercase = (
        {name.lower(): name for name in known_tutor_names} if known_tutor_names else None
    )

    capacities = {}
    seniority = {}
    unmatched = []

    for _, row in dataframe.iterrows():
        raw_name = row["Tutor Name"]
        if pd.isna(raw_name):
            continue

        name = str(raw_name).strip()
        if name_by_lowercase is not None:
            if name.lower() in name_by_lowercase:
                name = name_by_lowercase[name.lower()]
            else:
                unmatched.append(name)
                continue

        level = row["Seniority"]
        if not pd.isna(level):
            key = str(level).strip().lower()
            if key not in allowed_seniority:
                raise ValueError(
                    f"{name} has seniority {level!r} on the '{sheet_name}' sheet; "
                    "it must be Lead, Returning, or New."
                )
            seniority[name] = allowed_seniority[key]

        limit = row["Max Classes"]
        if not pd.isna(limit):
            try:
                is_whole = float(limit) == int(float(limit))
            except (TypeError, ValueError):
                is_whole = False
            if not is_whole or int(float(limit)) < 1:
                raise ValueError(
                    f"{name} has Max Classes {limit!r} on the '{sheet_name}' sheet; "
                    "it must be a whole number of 1 or more."
                )
            capacities[name] = int(float(limit))

    if unmatched:
        warnings.warn(
            f"These names on the '{sheet_name}' sheet match no tutor in the "
            f"Choices sheet and were ignored: {unmatched}"
        )

    return capacities, seniority


def tutor_names_from_classes(classes):
    """The distinct tutor names found in the Choices sheet, for matching
    against the Tutors sheet."""
    return sorted({name for c in classes for name, _ in c["candidates"]})


def _clean_link_group(value):
    """Tidy a Link Group cell: None for blank, otherwise the text with
    surrounding/repeated spaces removed."""
    if value is None or pd.isna(value):
        return None
    text = " ".join(str(value).split())
    return text or None


def link_group_key(label):
    """The form of a Link Group label used to decide whether two rows
    share a group: case-insensitive, with en/em dashes treated as plain
    hyphens (so "COMP 232 \u2013 A" and "comp 232 - a" are the same group)."""
    return label.replace("\u2013", "-").replace("\u2014", "-").casefold()


def load_real_choices(file_path, sheet_name="Choices Round 1"):
    """
    Parse the real class-oriented LRC placement sheet into a list of
    "classes needing a tutor" records, each with:

        {
            "class_id": "PSY 300 E3L",
            "tier_label": "Tier 1 EU",
            "tier_priority": 1,
            "candidates": [("Cassidy Rosenbaum", 1), ("Elizabeth Lanovaya", 1)],
            "cat_candidates": {"Elizabeth Lanovaya"},   # wrote "(CAT)" here
            "link_group": "COMP 232 - A",               # None when blank / no column
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

    # Optional "Link Group" column (found by its header name, so it can
    # sit anywhere - the far right is safest). Rows sharing a label are
    # treated as one lecture+lab family by link_groups.py.
    link_group_column = next(
        (c for c in dataframe.columns if str(c).strip().lower() == "link group"), None
    )

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

        # tutor -> (best choice tier, is_cat) they listed for THIS class.
        # If a tutor is accidentally listed twice, the better choice tier
        # wins; on a tie, the entry WITHOUT (CAT) wins (it is the less
        # restrictive one).
        best_for_tutor = {}

        for choice_tier, column in enumerate(PREFERENCE_COLUMNS, start=1):
            for raw_name, is_cat in _split_candidate_entries(row[column]):
                name = canonicalize(raw_name)
                entry = (choice_tier, is_cat)
                if name not in best_for_tutor or entry < best_for_tutor[name]:
                    best_for_tutor[name] = entry

        if not best_for_tutor:
            continue  # no candidates at all - disregard this class

        classes.append(
            {
                "class_id": class_id,
                "tier_label": tier_label,
                "tier_priority": tier_priority,
                "candidates": sorted(
                    ((name, entry[0]) for name, entry in best_for_tutor.items()),
                    key=lambda pair: pair[1],
                ),
                # Tutors who wrote "(CAT)" for this class (Canvas Attached
                # only). Kept separate from "candidates" so the existing
                # (name, choice_tier) pairs keep their shape.
                "cat_candidates": {
                    name for name, entry in best_for_tutor.items() if entry[1]
                },
                "link_group": (
                    _clean_link_group(row[link_group_column]) if link_group_column else None
                ),
            }
        )

    return classes