"""Glue between the uploaded workbook and the placement algorithm.

app.py calls run_placement(path) and gets back one plain dictionary that
the results page can render directly - no pandas objects, no algorithm
internals leak into the template.
"""

from link_groups import describe_groups, expand_results, solve_with_groups
from real_algorithm import (
    SENIORITY_RANK,
    find_alternative_optimal_assignments,
    is_cat_placement,
)
from real_excel_handler import (
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
    group_info, notices = describe_groups(classes, set(unstaffed_by_key))
    solved = solve_with_groups(classes, seniority_rank, capacities, group_info)
    section_rows = expand_results(solved["results"], solved["members_by_unit"])

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
        tutor_capacity=capacities,
        related_sections=related,
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
        unit_members = solved["members_by_unit"][sr["Unit"]]
        rows.append(
            {
                "class": sr["Class"],
                "tier": sr["Tier"],
                "tutor": sr["Assigned Tutor"],
                "choice": sr["Their Choice"],
                "cat": bool(sr["CAT"]),
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
        if r["choice"] in choice_counts:
            choice_counts[r["choice"]] += 1

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
            "cat": sum(1 for r in filled if r["cat"]),
            "contested": sum(1 for r in filled if r["alternatives"]),
            "tutors_placed": len(tutors),
        },
        "tutor_sheet_loaded": bool(capacities or seniority_labels),
        "notices": notices,
        "canceled": canceled,
        "link_groups_used": bool(group_info),
    }