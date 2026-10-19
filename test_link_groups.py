"""Checks for the Link Group (lecture + lab) logic. Run: python test_link_groups.py"""

import itertools
import random

from link_groups import (
    build_unit_classes,
    describe_groups,
    expand_results,
    solve_with_groups,
)
from algorithm import (
    match_real_choices_bruteforce,
    match_real_choices_fast,
)

TIERS = [("Tier 1", 1), ("Tier 2", 2), ("Tier 3", 3), ("CAT Only", 4)]


def random_classes(rng, n_classes, n_tutors, groups=True):
    tutors = [f"T{i}" for i in range(n_tutors)]
    classes = []
    for i in range(n_classes):
        label, pri = rng.choice(TIERS)
        k = rng.randint(1, min(4, n_tutors))
        names = rng.sample(tutors, k)
        cands = [(n, rng.randint(1, 3)) for n in names]
        cat = {n for n in names if rng.random() < 0.15}
        classes.append(
            {
                "class_id": f"C{i}",
                "tier_label": label,
                "tier_priority": pri,
                "candidates": sorted(cands, key=lambda p: p[1]),
                "cat_candidates": cat,
                "link_group": None,
            }
        )
    if groups:
        i = 0
        gnum = 0
        while i < n_classes - 1:
            if rng.random() < 0.6:
                size = rng.randint(2, 3)
                for c in classes[i : i + size]:
                    c["link_group"] = f"G{gnum}"
                gnum += 1
                i += size
            else:
                i += 1
    return classes, tutors


def test_size_aware_fast_matches_bruteforce(trials=150):
    rng = random.Random(1)
    for t in range(trials):
        classes, tutors = random_classes(rng, rng.randint(3, 8), rng.randint(2, 5), groups=False)
        for c in classes:
            c["size"] = rng.randint(1, 3)
        cap = {n: rng.randint(1, 3) for n in tutors}
        sen = {n: rng.randint(0, 3) for n in tutors}
        _, k_fast = match_real_choices_fast(classes, sen, cap)
        _, k_brute = match_real_choices_bruteforce(classes, sen, cap)
        assert k_fast == k_brute, (t, k_fast, k_brute)
    print(f"PASS: fast == brute force with unit sizes on {trials} random problems")


def all_split_best(classes, sen, cap, info):
    flippable = list(info)
    best = None
    for r in range(len(flippable) + 1):
        for subset in itertools.combinations(flippable, r):
            units, _ = build_unit_classes(classes, frozenset(subset), info)
            _, key = match_real_choices_fast(units, sen, cap)
            if best is None or key > best:
                best = key
    return best


def check_valid(classes, solved, cap):
    rows = expand_results(solved["results"], solved["members_by_unit"])
    by_id = {c["class_id"]: c for c in classes}
    load = {}
    for unit_id, members in solved["members_by_unit"].items():
        r = next(x for x in solved["results"] if x["Class"] == unit_id)
        if r["Assigned Tutor"]:
            load[r["Assigned Tutor"]] = load.get(r["Assigned Tutor"], 0) + 1
    for t, n in load.items():
        assert n <= cap.get(t, 2), (t, n)
    for row in rows:
        if row["Assigned Tutor"]:
            assert row["Assigned Tutor"] in dict(by_id[row["Class"]]["candidates"])
    assert len(rows) == len(classes)
    for unit_id, members in solved["members_by_unit"].items():
        r = next(x for x in solved["results"] if x["Class"] == unit_id)
        tutors = {r["Assigned Tutor"]}
        assert len(tutors) == 1


def test_search_matches_exhaustive_splits(trials=120):
    rng = random.Random(2)
    misses = 0
    for t in range(trials):
        classes, tutors = random_classes(rng, rng.randint(4, 9), rng.randint(2, 5))
        cap = {n: rng.randint(1, 3) for n in tutors}
        sen = {n: rng.randint(0, 3) for n in tutors}
        info, _ = describe_groups(classes)
        solved = solve_with_groups(classes, sen, cap, info)
        check_valid(classes, solved, cap)
        best = all_split_best(classes, sen, cap, {k: v for k, v in info.items() if v["mergeable"]})
        if solved["key"] != best:
            misses += 1
            assert solved["key"] < best
    print(f"PASS: single+pair split search vs every combination of splits: {trials - misses}/{trials} identical"
          + (f" ({misses} where a combination of splits was better)" if misses else ""))
    return misses


def mk(cid, cands, group=None, tier=("Tier 2", 2), cat=()):
    return {
        "class_id": cid, "tier_label": tier[0], "tier_priority": tier[1],
        "candidates": cands, "cat_candidates": set(cat), "link_group": group,
    }


def test_scenarios():
    # 1. A tutor who listed lecture+lab gets both, using one slot, so their
    #    second slot is still free for another class.
    classes = [
        mk("L", [("Ann", 1)], "A"), mk("LAB", [("Ann", 1)], "A"),
        mk("X", [("Ann", 2)]),
    ]
    solved = solve_with_groups(classes, {}, {"Ann": 2})
    rows = {r["Class"]: r["Assigned Tutor"] for r in expand_results(solved["results"], solved["members_by_unit"])}
    assert rows == {"L": "Ann", "LAB": "Ann", "X": "Ann"}, rows
    print("PASS: lecture+lab use ONE slot (Ann holds 3 sections with Max Classes 2)")

    # 2. Without the link, the same tutor could only hold 2 of those 3.
    plain = [dict(c, link_group=None) for c in classes]
    res, _ = match_real_choices_fast(plain, {}, {"Ann": 2})
    assert sum(1 for r in res if r["Assigned Tutor"]) == 2
    print("PASS: without the link the same setup fills only 2 of 3")

    # 3. A tutor who listed only the lab does not claim the family, and
    #    gets the lab when nobody can take the whole thing.
    classes = [
        mk("L", [("Ann", 1)], "A"), mk("LAB", [("Ann", 2), ("Bob", 1)], "A"),
    ]
    solved = solve_with_groups(classes, {}, {"Ann": 1, "Bob": 1})
    rows = {r["Class"]: r["Assigned Tutor"] for r in expand_results(solved["results"], solved["members_by_unit"])}
    assert rows == {"L": "Ann", "LAB": "Bob"} or rows == {"L": "Ann", "LAB": "Ann"}
    print("PASS: group is kept together or split by the usual priorities ->", rows)

    # 4. Split wins when the only full-coverage tutor is busy with a higher tier.
    classes = [
        mk("L", [("Ann", 1)], "A", tier=("Tier 3", 3)),
        mk("LAB", [("Ann", 1), ("Bob", 1)], "A", tier=("Tier 3", 3)),
        mk("T1", [("Ann", 1)], tier=("Tier 1", 1)),
    ]
    solved = solve_with_groups(classes, {}, {"Ann": 1, "Bob": 1})
    rows = {r["Class"]: r["Assigned Tutor"] for r in expand_results(solved["results"], solved["members_by_unit"])}
    assert rows["T1"] == "Ann" and rows["LAB"] == "Bob" and rows["L"] is None, rows
    print("PASS: Tier 1 still beats the link; the lab is split off to Bob")

    # 5. Notices.
    classes = [mk("A1", [("Ann", 1)], "Solo"), mk("B1", [("Ann", 1)], "Pair"), mk("B2", [("Bob", 1)], "pair")]
    info, notes = describe_groups(classes)
    assert any("only one class" in n for n in notes) and any("no tutor listed all" in n for n in notes), notes
    print("PASS: typos / uncoverable groups produce notices (case-insensitive matching)")


if __name__ == "__main__":
    test_size_aware_fast_matches_bruteforce()
    test_scenarios()
    test_search_matches_exhaustive_splits(400)


def test_unstaffed_linked_classes():
    """A label on a class with no tutor names is reported next to its partner."""
    import os
    import tempfile

    from openpyxl import Workbook

    from excel_handler import link_group_key, load_real_choices, load_unstaffed_linked_classes

    wb = Workbook()
    ws = wb.active
    ws.title = "Choices Round 1"
    ws.append(["Tier", "Subject", "Section", "Class Status", "1st Choice", "2nd Choice", "3rd Choice", "Link Group"])
    ws.append(["Tier 3", "PSY 300", "3", "Active", None, None, "Dylan Wikel (CAT)", "PSY 300 - C"])
    ws.append(["Tier 3", "PSY 300", "5L", "Active", None, None, None, "psy 300 – c"])
    ws.append(["Tier 3", "PSY 300", "6L", "Active", None, None, None, "PSY 300 - C"])
    ws.append(["Tier 3", "PSY 300", "7L", "Active", None, None, None, None])  # no label: ignored
    ws.append(["Tier 3", "ACCT 1", "1", "Active", "Ann Lee", None, None, "ACCT - A"])  # staffed, alone
    path = os.path.join(tempfile.mkdtemp(), "t.xlsx")
    wb.save(path)

    classes = load_real_choices(path)
    unstaffed = load_unstaffed_linked_classes(path)
    assert sorted(u["class_id"] for u in unstaffed) == ["PSY 300 5L", "PSY 300 6L"], unstaffed
    keys = {link_group_key(u["link_group"]) for u in unstaffed}
    assert len(keys) == 1  # spelling/dash/case differences still count as the same label

    _, notes = describe_groups(classes, keys)
    assert not any("PSY 300 - C" in n for n in notes), notes   # explained, so not flagged
    assert any("ACCT - A" in n for n in notes), notes          # a real lone label still is
    print("PASS: labelled classes with no tutor names are listed with their partner, not flagged as typos")


if __name__ == "__main__":
    test_unstaffed_linked_classes()