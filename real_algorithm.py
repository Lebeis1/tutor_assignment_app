from pathlib import Path

from real_excel_handler import load_real_choices, TIER_FILL_PRIORITY


PREFERENCE_SCORES = {1: 3, 2: 2, 3: 1}

# How many classes a single tutor can be assigned to at once.
TUTOR_CAPACITY = 2

# Optional. If you have a Lead/Returning/New roster for these tutors,
# pass it into match_real_choices(..., seniority_rank=your_dict) using
# these same values. Until then, every tutor is treated as equal
# seniority (the sheet itself has no seniority column to read from).
SENIORITY_RANK = {"Lead": 3, "Returning": 2, "New": 1}


def match_real_choices_bruteforce(classes, seniority_rank=None, show_trace=False):
    """
    Choose which classes get filled and by whom, out of a list of
    classes each with their own small set of candidate tutors (from
    load_real_choices).

    Priority order (each level is a HARD priority over the ones after
    it - a later level can never be improved at the cost of an earlier
    one):

        1. Fill as many Tier-1/Tier-1-EU classes as possible.
        2. Then as many Tier-2 classes as possible.
        3. Then as many Tier-3 classes as possible.
        4. Then as many CAT-Only classes as possible.
        5. Employ as many DISTINCT tutors as possible (every tutor who
           has at least one valid candidate class gets used at least
           once, even if it means giving them a lower choice, or giving
           another tutor their 2nd class instead of their top pick).
        6. Among ties on all of the above, maximize total preference
           score (how good a choice tier each filled class was for its
           tutor).
        7. Among ties on all of the above, prefer giving good outcomes
           to more senior tutors (only if seniority_rank is supplied).

    A tutor can fill up to TUTOR_CAPACITY classes (currently 2). A class
    is only ever filled by one of its own actual candidates - never left
    empty by choice if a candidate is available AND filling it wouldn't
    require sacrificing a higher-priority class elsewhere.

    This is a brute-force/backtracking search, same approach as
    algorithm.py: try "fill this class with candidate X", "...with
    candidate Y", ... or "leave this class unfilled", for every class,
    and keep the combination that scores highest by the priority order
    above. Includes branch-and-bound pruning (skip any partial
    combination that mathematically cannot beat the best complete
    combination found so far).
    """
    if seniority_rank is None:
        seniority_rank = {}

    priorities = sorted(set(TIER_FILL_PRIORITY.values()) | {c["tier_priority"] for c in classes})

    # Process most urgent tier first, and within a tier, the most
    # constrained (fewest-candidate) classes first. This doesn't change
    # the answer, just how quickly the search finds and prunes toward it.
    ordered_classes = sorted(
        classes, key=lambda c: (c["tier_priority"], len(c["candidates"]))
    )

    # Precompute, for the pruning bound, how many remaining classes (from
    # a given position onward) fall into each priority level.
    remaining_by_priority_from = [None] * (len(ordered_classes) + 1)
    remaining_by_priority_from[len(ordered_classes)] = {p: 0 for p in priorities}
    for i in range(len(ordered_classes) - 1, -1, -1):
        counts = dict(remaining_by_priority_from[i + 1])
        counts[ordered_classes[i]["tier_priority"]] += 1
        remaining_by_priority_from[i] = counts

    best = {"key": None, "assignment": None}

    def make_key(filled_by_priority, tutor_load, total_score, total_seniority):
        employed_count = len(tutor_load)
        return (
            tuple(filled_by_priority[p] for p in priorities)
            + (employed_count, total_score, total_seniority)
        )

    def upper_bound_key(index, filled_by_priority, tutor_load, total_score):
        remaining_counts = remaining_by_priority_from[index]
        optimistic_filled = {
            p: filled_by_priority[p] + remaining_counts[p] for p in priorities
        }
        remaining_classes = len(ordered_classes) - index
        # Best case: every remaining class employs a brand-new tutor.
        optimistic_employed = len(tutor_load) + remaining_classes
        optimistic_score = total_score + PREFERENCE_SCORES[1] * remaining_classes
        # Seniority bound is left unbounded since it's a low-stakes
        # tie-breaker only.
        return tuple(optimistic_filled[p] for p in priorities) + (
            optimistic_employed,
            optimistic_score,
            float("inf"),
        )

    def backtrack(index, tutor_load, filled_by_priority, assignment, total_score, total_seniority):
        if best["key"] is not None:
            bound = upper_bound_key(index, filled_by_priority, tutor_load, total_score)
            if bound < best["key"]:
                return

        if index == len(ordered_classes):
            key = make_key(filled_by_priority, tutor_load, total_score, total_seniority)
            if best["key"] is None or key > best["key"]:
                best["key"] = key
                best["assignment"] = dict(assignment)
            return

        class_record = ordered_classes[index]
        tier_priority = class_record["tier_priority"]

        for tutor_name, choice_tier in class_record["candidates"]:
            if tutor_load.get(tutor_name, 0) >= TUTOR_CAPACITY:
                continue

            preference_points = PREFERENCE_SCORES[choice_tier]
            rank = seniority_rank.get(tutor_name, 0)

            tutor_load[tutor_name] = tutor_load.get(tutor_name, 0) + 1
            assignment[class_record["class_id"]] = (tutor_name, choice_tier)
            filled_by_priority[tier_priority] += 1

            if show_trace:
                print(
                    f"{class_record['class_id']} -> {tutor_name} "
                    f"(their choice {choice_tier}, tier {class_record['tier_label']})"
                )

            backtrack(
                index + 1,
                tutor_load,
                filled_by_priority,
                assignment,
                total_score + preference_points,
                total_seniority + rank * preference_points,
            )

            filled_by_priority[tier_priority] -= 1
            del assignment[class_record["class_id"]]
            tutor_load[tutor_name] -= 1
            if tutor_load[tutor_name] == 0:
                del tutor_load[tutor_name]

        # Also always consider leaving this class unfilled.
        backtrack(
            index + 1,
            tutor_load,
            filled_by_priority,
            assignment,
            total_score,
            total_seniority,
        )

    initial_filled = {p: 0 for p in priorities}
    backtrack(0, {}, initial_filled, {}, 0, 0)

    results = []
    for class_record in ordered_classes:
        assignment_entry = best["assignment"].get(class_record["class_id"])

        if assignment_entry is None:
            results.append(
                {
                    "Class": class_record["class_id"],
                    "Tier": class_record["tier_label"],
                    "Assigned Tutor": None,
                    "Their Choice": None,
                }
            )
        else:
            tutor_name, choice_tier = assignment_entry
            results.append(
                {
                    "Class": class_record["class_id"],
                    "Tier": class_record["tier_label"],
                    "Assigned Tutor": tutor_name,
                    "Their Choice": choice_tier,
                }
            )

    results.sort(key=lambda r: r["Class"])

    return results, best["key"]


def match_real_choices_fast(classes, seniority_rank=None):
    """
    Same priority rules and output as match_real_choices_bruteforce,
    but solved EXACTLY via weighted bipartite matching
    (scipy.optimize.linear_sum_assignment) instead of brute-force
    search. Finds the true mathematical optimum, instantly, regardless
    of how many classes or tutors are involved.

    How the priority levels are enforced with a single matching call:
    each level (tier priority, then "every tutor gets used at least
    once", then preference score, then seniority) gets its own "weight"
    that is deliberately made far larger than the combined maximum
    possible contribution of every level below it. Maximizing total
    weighted benefit then automatically reproduces the exact same hard
    priority order as the brute-force version - a single extra Tier-1
    class filled always outweighs any possible number of Tier-2/3/CAT
    fills, employing an extra tutor, or preference-score differences,
    because its weight is mathematically guaranteed to be bigger than
    all of those combined - and so on down the hierarchy.

    The "employ every tutor" rule is implemented by giving ONLY a
    tutor's FIRST capacity slot an extra bonus for being used at all;
    their second slot carries no such bonus. This makes "spread the
    work so a new tutor gets used" worth more than "give someone their
    2nd class", without making it worth more than filling a
    higher-priority tier.
    """
    import numpy as np
    from scipy.optimize import linear_sum_assignment

    if seniority_rank is None:
        seniority_rank = {}

    num_classes = len(classes)
    priorities = sorted(set(TIER_FILL_PRIORITY.values()) | {c["tier_priority"] for c in classes})

    # Weight for each level, built from the bottom up so every level
    # strictly dominates everything below it, however many classes exist.
    max_seniority_contribution = max(SENIORITY_RANK.values(), default=1) * max(PREFERENCE_SCORES.values())
    max_preference_contribution = max(PREFERENCE_SCORES.values())

    seniority_weight = 1
    preference_weight = (max_seniority_contribution * num_classes + 1) * seniority_weight
    # "Employ a new tutor" must dominate every possible preference-score
    # difference across the whole problem (at most 3 points per class).
    employment_weight = (max_preference_contribution * num_classes + 1) * preference_weight

    tier_weight = {}
    running = (1 * num_classes + 1) * employment_weight  # at most 1 "new employment" per class
    for p in reversed(priorities):  # build from LEAST urgent up to MOST urgent
        tier_weight[p] = running
        running = running * (num_classes + 1)

    # Build the list of tutor "slots" - TUTOR_CAPACITY interchangeable
    # copies per tutor, each tagged with which capacity slot (0-indexed)
    # it is - so this becomes an ordinary 1-to-1 assignment problem
    # between classes and slots, while still knowing which slot is a
    # tutor's FIRST (the one eligible for the employment bonus).
    tutor_names = sorted({name for c in classes for name, _ in c["candidates"]})
    slots = [
        (name, slot_number)
        for name in tutor_names
        for slot_number in range(TUTOR_CAPACITY)
    ]
    num_slots = len(slots)

    # Pad to a square matrix: a dummy column per class (lets a class opt
    # out and stay unfilled) and a dummy row per slot (lets a slot opt
    # out and stay unused). This way the solver is never FORCED into an
    # invalid class/tutor pairing just to fill out the matrix shape.
    size = num_classes + num_slots
    NEG_SENTINEL = -(tier_weight[priorities[0]] * 10)  # worse than any real outcome
    benefit = np.full((size, size), NEG_SENTINEL, dtype=np.float64)

    # Real class rows / real slot columns: top-left block.
    for row, class_record in enumerate(classes):
        candidate_tiers = dict(class_record["candidates"])  # tutor -> choice_tier
        for col, (tutor_name, slot_number) in enumerate(slots):
            if tutor_name not in candidate_tiers:
                continue
            choice_tier = candidate_tiers[tutor_name]
            preference_points = PREFERENCE_SCORES[choice_tier]
            rank = seniority_rank.get(tutor_name, 0)
            employment_bonus = employment_weight if slot_number == 0 else 0

            value = (
                tier_weight[class_record["tier_priority"]]
                + employment_bonus
                + preference_points * preference_weight
                + (rank * preference_points) * seniority_weight
            )
            benefit[row, col] = value

    # Any class row paired with any dummy column = "leave unfilled" (0).
    benefit[:num_classes, num_slots:] = 0
    # Any dummy row paired with any real slot column = "slot unused" (0).
    benefit[num_classes:, :num_slots] = 0
    # Dummy-dummy pairings are irrelevant filler, 0 is fine.
    benefit[num_classes:, num_slots:] = 0

    row_indices, col_indices = linear_sum_assignment(benefit, maximize=True)

    assignment = {}
    for row, col in zip(row_indices, col_indices):
        if row >= num_classes:
            continue  # a dummy row, not a real class
        if col >= num_slots:
            continue  # matched to a dummy column - left unfilled
        tutor_name, _slot_number = slots[col]
        choice_tier = dict(classes[row]["candidates"])[tutor_name]
        assignment[classes[row]["class_id"]] = (tutor_name, choice_tier)

    results = []
    filled_by_priority = {p: 0 for p in priorities}
    total_score = 0
    total_seniority = 0

    for class_record in classes:
        entry = assignment.get(class_record["class_id"])
        if entry is None:
            results.append(
                {
                    "Class": class_record["class_id"],
                    "Tier": class_record["tier_label"],
                    "Assigned Tutor": None,
                    "Their Choice": None,
                }
            )
        else:
            tutor_name, choice_tier = entry
            preference_points = PREFERENCE_SCORES[choice_tier]
            filled_by_priority[class_record["tier_priority"]] += 1
            total_score += preference_points
            total_seniority += seniority_rank.get(tutor_name, 0) * preference_points
            results.append(
                {
                    "Class": class_record["class_id"],
                    "Tier": class_record["tier_label"],
                    "Assigned Tutor": tutor_name,
                    "Their Choice": choice_tier,
                }
            )

    results.sort(key=lambda r: r["Class"])
    employed_count = len({r["Assigned Tutor"] for r in results if r["Assigned Tutor"]})
    key = (
        tuple(filled_by_priority[p] for p in priorities)
        + (employed_count, total_score, total_seniority)
    )

    return results, key


if __name__ == "__main__":
    import sys

    project_folder = Path(__file__).parent

    if len(sys.argv) > 1:
        file_path = Path(sys.argv[1])
    else:
        file_path = project_folder / "sample_data" / "real_choices_sample.xlsx"

    classes = load_real_choices(file_path)
    results, key = match_real_choices_fast(classes)

    filled = [r for r in results if r["Assigned Tutor"] is not None]
    unfilled = [r for r in results if r["Assigned Tutor"] is None]

    print(f"\n{len(filled)} of {len(results)} candidate-having classes filled\n")
    print("=" * 75)
    for r in filled:
        print(f"{r['Class']} ({r['Tier']}) -> {r['Assigned Tutor']} [their choice {r['Their Choice']}]")
    print("=" * 75)

    if unfilled:
        print(f"\n{len(unfilled)} classes could NOT be filled (not enough tutors):")
        for r in unfilled:
            print(f"  {r['Class']} ({r['Tier']})")