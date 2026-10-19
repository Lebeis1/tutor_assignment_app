"""Lecture + lab "Link Groups".

Rows in the Choices sheet that share a Link Group label are one course
offering (e.g. a lecture and its lab). The rules, as agreed:

  * A linked family counts as ONE class toward a tutor's Max Classes,
    but still counts as every section it contains for tier fills, CAT
    avoidance and preference score.
  * Only a tutor who listed EVERY section of the family can take it as
    a whole. A tutor who listed just the lecture or just the lab is not
    a candidate for the family.
  * If a family would work out better split up (for example nobody who
    listed all of it is free, but one tutor can take the lecture and
    another the lab), it is split and its sections are matched on their
    own, each using one slot.

The matching itself is unchanged: this module just turns a family into
a single "unit" class (size = number of sections) before calling the
solver, and expands the answer back to one row per section afterwards.
"""

import itertools
import math

from algorithm import is_cat_placement, match_real_choices_fast
from excel_handler import link_group_key

# Above this many splittable families, only single splits are tried.
MAX_PAIR_SEARCH = 14


def find_groups(classes):
    """key -> {"label": str, "members": [class records]}, only for rows
    that have a Link Group, in sheet order."""
    groups = {}
    for record in classes:
        label = record.get("link_group")
        if not label:
            continue
        groups.setdefault(link_group_key(label), {"label": label, "members": []})["members"].append(record)
    return groups


def _full_coverage_tutors(members):
    """Tutors who listed every section in the family."""
    sets = [{name for name, _ in m["candidates"]} for m in members]
    return set.intersection(*sets) if sets else set()


def describe_groups(classes, unstaffed_keys=frozenset()):
    """
    Look at the Link Group column and report, for each label used:
    which sections it has, which tutors listed all of them, and whether
    it can be merged. Also returns plain-language notices about anything
    that looks like a mistake in the sheet. unstaffed_keys: labels that
    also appear on classes with no tutor names (so a lone labelled class
    is expected there, not a typo).

    Returns (groups, notices) where groups maps key -> info dict.
    """
    info = {}
    notices = []
    single_use = []
    for key, group in find_groups(classes).items():
        members = group["members"]
        ids = [m["class_id"] for m in members]
        if len(members) == 1:
            if key in unstaffed_keys:
                continue  # its partners simply have no tutor names - shown on the page
            single_use.append(f"\u201c{group['label']}\u201d ({ids[0]})")
            continue

        full = _full_coverage_tutors(members)
        tiers = {m["tier_label"] for m in members}
        mergeable = bool(full)
        if not mergeable:
            notices.append(
                f"Link Group “{group['label']}” ({', '.join(ids)}): no tutor listed all of "
                "these classes, so they are placed separately."
            )
        elif len(tiers) > 1:
            notices.append(
                f"Link Group “{group['label']}” mixes tiers ({', '.join(sorted(tiers))}); "
                "when kept together it is ranked by its most urgent tier."
            )
        info[key] = {
            "label": group["label"],
            "members": members,
            "member_ids": ids,
            "full_tutors": full,
            "mergeable": mergeable,
        }
    if single_use:
        notices.append(
            "These Link Groups are used by only one class with tutor names, so they have no "
            "effect (fine if the class is meant to stand alone, otherwise check the spelling): "
            + ", ".join(single_use) + "."
        )
    return info, notices


def build_unit_classes(classes, split_keys=frozenset(), group_info=None):
    """
    Turn the class list into solver "units": every mergeable, not-split
    family becomes ONE class of size = number of sections; everything
    else passes through unchanged.

    Returns (units, members_by_unit) where members_by_unit maps each
    unit's class_id to the list of original class records it covers.
    """
    if group_info is None:
        group_info, _ = describe_groups(classes)

    units = []
    members_by_unit = {}
    emitted = set()

    for record in classes:
        label = record.get("link_group")
        key = link_group_key(label) if label else None
        group = group_info.get(key)

        if group is None or not group["mergeable"] or key in split_keys:
            units.append(record)
            members_by_unit[record["class_id"]] = [record]
            continue

        if key in emitted:
            continue
        emitted.add(key)

        members = group["members"]
        candidates = []
        for tutor in group["full_tutors"]:
            choices = [dict(m["candidates"])[tutor] for m in members]
            # Round the average choice toward the WORSE choice, so a
            # merged family never looks happier than its parts.
            candidates.append((tutor, math.ceil(sum(choices) / len(choices))))
        candidates.sort(key=lambda pair: (pair[1], pair[0]))

        urgent = min(members, key=lambda m: m["tier_priority"])
        unit_id = " + ".join(group["member_ids"])
        units.append(
            {
                "class_id": unit_id,
                "tier_label": urgent["tier_label"],
                "tier_priority": urgent["tier_priority"],
                "candidates": candidates,
                "cat_candidates": set().union(*(m["cat_candidates"] for m in members))
                & group["full_tutors"],
                "size": len(members),
                "link_group": group["label"],
            }
        )
        members_by_unit[unit_id] = list(members)

    return units, members_by_unit


def solve_with_groups(classes, seniority_rank=None, tutor_capacity=None, group_info=None):
    """
    Solve with Link Groups. Starts with every mergeable family kept
    together, then tries splitting each family whose split could help
    (a tutor listed some of its sections but not all), keeping a split
    only when it strictly improves the result by the usual priority
    order, and repeating until no single split helps.

    This tries every single split and every PAIR of splits, which is
    thorough for ordinary sheets but is not a proof that no larger
    combination of splits could do better (test_link_groups.py checks it
    against exhaustive search on random problems).

    Returns a dict: units, members_by_unit, results (one row per unit),
    key, split_keys (families that were split), group_info.
    """
    if group_info is None:
        group_info, _ = describe_groups(classes)

    def solve(split_keys):
        units, members = build_unit_classes(classes, split_keys, group_info)
        results, key = match_real_choices_fast(units, seniority_rank, tutor_capacity)
        return units, members, results, key

    split_keys = set()
    units, members, results, best_key = solve(split_keys)

    # Any mergeable family might be better split: not only when some
    # tutor listed part of it, but also when splitting lets a second
    # tutor (who would otherwise get no class at all) take a section.
    flippable = [k for k, g in group_info.items() if g["mergeable"]]

    improved = True
    while improved:
        improved = False
        # Single splits first; once none helps, try splitting two
        # families together (two families can compete for the same
        # tutor, so neither split helps alone but both together do).
        # Pairs are skipped on sheets with a huge number of candidates
        # to keep the page responsive.
        trials = [(k,) for k in flippable]
        trials_pairs = list(itertools.combinations(flippable, 2)) if len(flippable) <= MAX_PAIR_SEARCH else []
        for stage in (trials, trials_pairs):
            for combo in stage:
                if any(k in split_keys for k in combo):
                    continue
                trial = split_keys | set(combo)
                t_units, t_members, t_results, t_key = solve(trial)
                if t_key > best_key:
                    split_keys = trial
                    units, members, results, best_key = t_units, t_members, t_results, t_key
                    improved = True
            if improved:
                break

    return {
        "units": units,
        "members_by_unit": members,
        "results": results,
        "key": best_key,
        "split_keys": split_keys,
        "group_info": group_info,
    }


def expand_results(unit_results, members_by_unit):
    """One row per ORIGINAL class (section), whichever way it was solved."""
    rows = []
    for r in unit_results:
        members = members_by_unit[r["Class"]]
        for m in members:
            tutor = r["Assigned Tutor"]
            rows.append(
                {
                    "Class": m["class_id"],
                    "Tier": m["tier_label"],
                    "Assigned Tutor": tutor,
                    "Their Choice": dict(m["candidates"])[tutor] if tutor else None,
                    "CAT": bool(tutor and is_cat_placement(m, tutor)),
                    "Unit": r["Class"],
                    "Link Group": m.get("link_group"),
                    "Kept Together": len(members) > 1,
                }
            )
    rows.sort(key=lambda row: row["Class"])
    return rows