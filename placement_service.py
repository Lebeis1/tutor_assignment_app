"""Glue between the uploaded workbook and the placement algorithm.

app.py calls run_placement(path) and gets back one plain dictionary that
the results page can render directly - no pandas objects, no algorithm
internals leak into the template.
"""

from link_groups import describe_groups, expand_results, solve_with_groups
from algorithm import (
    DEFAULT_TUTOR_CAPACITY,
    SENIORITY_RANK,
    find_alternative_optimal_assignments,
    is_cat_placement,
)
from excel_handler import (
    find_canceled_class_ids,
    find_related_sections,
    link_group_key,
    load_real_choices,
    load_unstaffed_linked_classes,
    load_tutor_info,
    tutor_names_from_classes,
)

TIER_ORDER = ["Tier 1", "Tier 1 EU", "Tier 2", "Tier 3", "CAT Only"]


def _tier_sort_key(tier):
    return TIER_ORDER.index(tier) if tier in TIER_ORDER else len(TIER_ORDER)


def _apply_locks(classes, capacities):
    """
    Work out the "(locked)" placements.

    Returns (rows, notices, solver_capacity, locked_tutors, group_keys):
      rows           - one result row per locked class, in the same shape
                       expand_results() produces (plus a second tutor and
                       the locked names).
      notices        - plain-language things worth a look.
      solver_capacity- Max Classes per tutor with locked classes already
                       subtracted, for the rest of the matching.
      locked_tutors  - everyone holding a locked class.
      group_keys     - Link Group keys that contain a locked section.
    """
    rows, notices = [], []
    held = {}  # tutor -> set of "class units" they are locked into
    group_keys = set()
    group_notes = {}

    for record in classes:
        names = record.get("locked_candidates") or set()
        if not names:
            continue
        choice = dict(record["candidates"])
        ordered = sorted(names, key=lambda n: (choice[n], n.lower()))
        kept, dropped = ordered[:2], ordered[2:]
        label = record.get("link_group")
        key = link_group_key(label) if label else None
        if key:
            group_keys.add(key)
            group_notes.setdefault(key, (label, []))[1].append((record["class_id"], kept[0]))
        for n in kept:
            held.setdefault(n, set()).add(key or record["class_id"])
        if len(ordered) > 1:
            notices.append(
                f"{record['class_id']}: {' and '.join(kept)} are both locked to this class, so "
                "both are placed there"
                + (f" ({', '.join(dropped)} could not be shown: a class holds two tutors)" if dropped else "")
                + "."
            )
        second = kept[1] if len(kept) > 1 else None
        rows.append(
            {
                "Class": record["class_id"],
                "Tier": record["tier_label"],
                "Assigned Tutor": kept[0],
                "Their Choice": choice[kept[0]],
                "CAT": is_cat_placement(record, kept[0]),
                "Second Tutor": second,
                "Second Choice": choice[second] if second else None,
                "Second CAT": bool(second and is_cat_placement(record, second)),
                "Locked": kept,
                "Unit": record["class_id"],
                "Link Group": label,
                "Kept Together": False,
            }
        )

    for key, (label, items) in group_notes.items():
        locked_ids = {cid for cid, _ in items}
        others = [
            c["class_id"] for c in classes
            if c.get("link_group") and link_group_key(c["link_group"]) == key
            and c["class_id"] not in locked_ids
        ]
        if not others:
            continue  # every staffed section of the group is locked: nothing to explain
        placed = ", ".join(f"{cid} (locked to {t})" for cid, t in items)
        notices.append(
            f"Link Group \u201c{label}\u201d has a locked section: {placed}. Its locked sections are "
            "placed as the sheet says and the rest are matched on their own, so a tutor who also "
            "takes another section of that group uses one more of their Max Classes."
        )

    solver_capacity = dict(capacities)
    for name, units in held.items():
        limit = capacities.get(name, DEFAULT_TUTOR_CAPACITY)
        if len(units) > limit:
            notices.append(
                f"{name} is locked to {len(units)} classes but their Max Classes is {limit}. "
                "All locks are kept, so they show as over their maximum."
            )
        solver_capacity[name] = max(0, limit - len(units))

    return rows, notices, solver_capacity, set(held), group_keys


def run_placement(file_path):
    canceled = find_canceled_class_ids(file_path)
    classes = load_real_choices(file_path)
    if not classes:
        raise ValueError("No classes with tutor names were found in the 'Choices Round 1' sheet.")

    capacities, seniority_labels = load_tutor_info(
        file_path, known_tutor_names=tutor_names_from_classes(classes)
    )
    seniority_rank = {n: SENIORITY_RANK[label] for n, label in seniority_labels.items()}

    # Lecture + lab families from the optional "Link Group" column.
    unstaffed_by_key = {}
    for item in load_unstaffed_linked_classes(file_path):
        unstaffed_by_key.setdefault(link_group_key(item["link_group"]), []).append(item["class_id"])

    # "(locked)": those tutors are fixed to those classes. The locked
    # classes are taken out of the matching, each locked tutor's Max
    # Classes shrinks by what they are already holding, and they no
    # longer count as "a tutor still needing a first class".
    locked_rows, lock_notices, solver_capacity, locked_tutors, locked_group_keys = _apply_locks(
        classes, capacities
    )
    locked_ids = {r["Class"] for r in locked_rows}
    free_classes = [c for c in classes if c["class_id"] not in locked_ids]

    group_info, notices = describe_groups(
        free_classes, set(unstaffed_by_key) | locked_group_keys
    )
    notices = lock_notices + notices
    solved = solve_with_groups(
        free_classes, seniority_rank, solver_capacity, group_info,
        already_employed=frozenset(locked_tutors),
    )
    section_rows = expand_results(solved["results"], solved["members_by_unit"]) + locked_rows

    # With an explicit Link Group column, that is the source of truth;
    # the older "looks related" guess is only used when the column is
    # absent, and only to nudge between equally good options.
    related = {}
    if not any(c.get("link_group") for c in classes):
        try:
            related = find_related_sections(file_path)
        except Exception:  # grouping is only a nudge - never block the run
            related = {}

    alternatives = find_alternative_optimal_assignments(
        solved["units"],
        seniority_rank=seniority_rank,
        tutor_capacity=solver_capacity,
        related_sections=related,
        already_employed=frozenset(locked_tutors),
    )
    alt_by_unit = {a["Class"]: a for a in alternatives}
    class_by_id = {c["class_id"]: c for c in classes}

    for key in sorted(solved["split_keys"]):
        info = group_info[key]
        placed = {r["Class"]: r["Assigned Tutor"] for r in section_rows}
        parts = ", ".join(f"{cid} \u2192 {placed[cid] or 'open'}" for cid in info["member_ids"])
        notices.append(
            f"\u201c{info['label']}\u201d was split up ({parts}): placing its sections "
            "separately fills more classes or gives more tutors a class than keeping them together."
        )

    rows = []
    for sr in section_rows:
        record = class_by_id[sr["Class"]]
        alt = alt_by_unit.get(sr["Unit"], {})
        options = []
        for o in alt.get("options", []):
            if o["Assigned Tutor"] == sr["Assigned Tutor"]:
                continue
            options.append(
                {
                    "tutor": o["Assigned Tutor"],
                    "choice": dict(record["candidates"]).get(o["Assigned Tutor"], o["Their Choice"]),
                    "cat": is_cat_placement(record, o["Assigned Tutor"]),
                    "recommended": o["recommended"],
                }
            )
        unit_members = solved["members_by_unit"].get(sr["Unit"], [record])
        rows.append(
            {
                "class": sr["Class"],
                "subject": record["subject"],
                "section": record["section"],
                "tier": sr["Tier"],
                "tutor": sr["Assigned Tutor"],
                "choice": sr["Their Choice"],
                "cat": bool(sr["CAT"]),
                "tutor2": sr.get("Second Tutor"),
                "choice2": sr.get("Second Choice"),
                "cat2": bool(sr.get("Second CAT")),
                "locked": sr.get("Locked", []),
                "alternatives": options,
                "num_candidates": len(record["candidates"]),
                "candidates": [n for n, _ in record["candidates"]],
                "unit": sr["Unit"],
                "link_group": sr["Link Group"],
                "kept_together": sr["Kept Together"],
                "linked_with": [m["class_id"] for m in unit_members if m["class_id"] != sr["Class"]],
            }
        )
    rows.sort(key=lambda row: (_tier_sort_key(row["tier"]), row["class"]))

    filled = [r for r in rows if r["tutor"]]
    unfilled = [r for r in rows if not r["tutor"]]

    by_tutor = {}
    for r in filled:
        by_tutor.setdefault(r["tutor"], []).append(r)
        if r["tutor2"]:
            by_tutor.setdefault(r["tutor2"], []).append(r)
    tutors = [
        {
            "name": name,
            "classes": sorted(items, key=lambda x: x["class"]),
            # A lecture+lab kept together uses ONE slot, so count units.
            "load": len({i["unit"] for i in items}),
            "max": capacities.get(name, 2),
            "seniority": seniority_labels.get(name, ""),
        }
        for name, items in sorted(by_tutor.items(), key=lambda kv: kv[0].lower())
    ]

    all_candidates = {n for c in classes for n, _ in c["candidates"]}
    unplaced_tutors = sorted(all_candidates - set(by_tutor), key=str.lower)

    tier_summary = []
    for tier in sorted({r["tier"] for r in rows}, key=_tier_sort_key):
        total = sum(1 for r in rows if r["tier"] == tier)
        done = sum(1 for r in filled if r["tier"] == tier)
        tier_summary.append({"tier": tier, "filled": done, "total": total})

    choice_counts = {1: 0, 2: 0, 3: 0}
    for r in filled:
        for ch in (r["choice"], r["choice2"]):
            if ch in choice_counts:
                choice_counts[ch] += 1

    # Everything the in-browser editor needs, so the page can recompute
    # warnings and counts live as the user moves names around.
    group_members = {}
    for c in classes:
        if c.get("link_group"):
            group_members.setdefault(link_group_key(c["link_group"]), []).append(c["class_id"])
    payload_classes = []
    for r in rows:
        record = class_by_id[r["class"]]
        key = link_group_key(record["link_group"]) if record.get("link_group") else None
        siblings = [i for i in group_members.get(key, []) if i != r["class"]] if key else []
        unstaffed = unstaffed_by_key.get(key, []) if key else []
        payload_classes.append(
            {
                "id": r["class"],
                "tier": r["tier"],
                "tutor": r["tutor"],
                "extra": r["tutor2"],
                "locked": r["locked"],
                "subject": r["subject"],
                "section": r["section"],
                "group": record.get("link_group") if (siblings or unstaffed) else None,
                "siblings": siblings,
                "unstaffed": unstaffed,
                "cands": {n: ch for n, ch in record["candidates"]},
                "cat": [n for n, _ in record["candidates"] if is_cat_placement(record, n)],
                "alts": r["alternatives"],
            }
        )
    payload_tutors = [
        {"name": n, "max": capacities.get(n, 2), "seniority": seniority_labels.get(n, "")}
        for n in sorted(all_candidates, key=str.lower)
    ]

    return {
        "payload": {"classes": payload_classes, "tutors": payload_tutors, "tier_order": TIER_ORDER, "canceled": canceled},
        "rows": rows,
        "unfilled": unfilled,
        "tutors": tutors,
        "unplaced_tutors": unplaced_tutors,
        "tier_summary": tier_summary,
        "choice_counts": choice_counts,
        "stats": {
            "total": len(rows),
            "filled": len(filled),
            "unfilled": len(unfilled),
            "cat": sum(1 for r in filled if r["cat"]) + sum(1 for r in filled if r["cat2"]),
            "locked": sum(len(r["locked"]) for r in rows),
            "contested": sum(1 for r in filled if r["alternatives"]),
            "tutors_placed": len(tutors),
        },
        "tutor_sheet_loaded": bool(capacities or seniority_labels),
        "notices": notices,
        "canceled": canceled,
        "link_groups_used": bool(group_info),
    }