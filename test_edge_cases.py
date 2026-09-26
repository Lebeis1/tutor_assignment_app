from itertools import permutations

import pandas as pd

from algorithm import brute_force_match


def make_tutors(rows):
    return pd.DataFrame(
        rows,
        columns=[
            "Tutor Name",
            "Seniority",
            "First Choice",
            "Second Choice",
            "Third Choice",
        ],
    )


def make_classes(names):
    return pd.DataFrame(
        {
            "Class Name": names,
            "Minimum Tutors": [1] * len(names),
            "Maximum Tutors": [1] * len(names),
        }
    )


def test_forces_lower_choice_when_top_choices_collide():
    """
    Alice and Bob both want Chemistry first. Only one Chemistry slot
    exists, so one of them must be pushed to a lower choice instead of
    the algorithm failing or double-booking Chemistry.
    """
    tutor_prefs = {
        "Alice": ["Chemistry", "Biology", "Physics"],
        "Bob": ["Chemistry", "Physics", "Biology"],
        "Carl": ["Physics", "Chemistry", "Biology"],
    }
    tutors = make_tutors(
        [[name, "New", *prefs] for name, prefs in tutor_prefs.items()]
    )
    classes = make_classes(["Chemistry", "Biology", "Physics"])

    results, score = brute_force_match(tutors, classes)
    assigned = {r["Tutor Name"]: r["Assigned Class"] for r in results}

    # Independently brute-force this tiny case with plain permutations,
    # so the expected score isn't just a hand-typed (and possibly wrong)
    # number - it's derived the same way verify.py derives it.
    scores_by_rank = {0: 3, 1: 2, 2: 1}
    best_possible = -1
    for permutation in permutations(classes["Class Name"]):
        assignment = dict(zip(tutor_prefs.keys(), permutation))
        total = 0
        for name, assigned_class in assignment.items():
            if assigned_class not in tutor_prefs[name]:
                total = None
                break
            total += scores_by_rank[tutor_prefs[name].index(assigned_class)]
        if total is not None and total > best_possible:
            best_possible = total

    assert set(assigned.values()) == {"Chemistry", "Biology", "Physics"}
    assert not (assigned["Alice"] == "Chemistry" and assigned["Bob"] == "Chemistry")
    assert score == best_possible
    print("PASS: forces a lower choice instead of failing or double-booking")


def test_unequal_tutor_and_class_counts_is_rejected():
    tutors = make_tutors([["Alice", "New", "Chemistry", "Biology", "Physics"]])
    classes = make_classes(["Chemistry", "Biology"])

    try:
        brute_force_match(tutors, classes)
        raise AssertionError("Expected a ValueError for mismatched counts.")
    except ValueError:
        print("PASS: rejects mismatched tutor/class counts")


def test_class_nobody_chose_is_reported_by_name():
    tutors = make_tutors(
        [
            ["Alice", "New", "Chemistry", "Biology", "Physics"],
            ["Bob", "New", "Biology", "Chemistry", "Physics"],
            ["Carl", "New", "Physics", "Chemistry", "Biology"],
            ["Denis", "New", "Chemistry", "Physics", "Biology"],
        ]
    )
    # "Calculus" exists as a class but no tutor ever lists it, so it can
    # never legally be filled - the error should name it specifically.
    classes = make_classes(["Chemistry", "Biology", "Physics", "Calculus"])

    try:
        brute_force_match(tutors, classes)
        raise AssertionError("Expected a ValueError naming the unreachable class.")
    except ValueError as error:
        assert "Calculus" in str(error)
        print("PASS: names the unreachable class in the error message")


def test_seniority_only_breaks_genuine_ties():
    """
    T1 (Lead) and T2 (New) have IDENTICAL preferences: X first, Y
    second, Z third. T3 (Returning) wants Z first, Y second, X third.

    Whichever of T1/T2 gets X and which gets Y, the total preference
    score comes out the same (3 + 2 either way) - a genuine tie. Only
    seniority should decide who gets the better class: T1 (Lead)
    should win X over T2 (New).
    """
    tutors = make_tutors(
        [
            ["T1_Lead", "Lead", "X", "Y", "Z"],
            ["T2_New", "New", "X", "Y", "Z"],
            ["T3", "Returning", "Z", "Y", "X"],
        ]
    )
    classes = make_classes(["X", "Y", "Z"])

    results, score = brute_force_match(tutors, classes)
    assigned = {r["Tutor Name"]: r["Assigned Class"] for r in results}

    assert score == 8  # 3 (X) + 2 (Y) + 3 (Z), same regardless of who wins the tie
    assert assigned["T3"] == "Z"  # T3 has no competitor, always gets its 1st choice
    assert assigned["T1_Lead"] == "X", "Seniority should have given the Lead the tie"
    assert assigned["T2_New"] == "Y"
    print("PASS: seniority correctly breaks a genuine scoring tie")


if __name__ == "__main__":
    test_forces_lower_choice_when_top_choices_collide()
    test_unequal_tutor_and_class_counts_is_rejected()
    test_class_nobody_chose_is_reported_by_name()
    test_seniority_only_breaks_genuine_ties()
    print("\nAll edge-case tests passed.")