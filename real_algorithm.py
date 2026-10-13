from pathlib import Path

from real_excel_handler import (
    TIER_FILL_PRIORITY,
    load_real_choices,
    load_tutor_info,
    tutor_names_from_classes,
)


PREFERENCE_SCORES = {1: 3, 2: 2, 3: 1}

# Default cap on how many classes a tutor can be assigned, used for any
# tutor not given a specific value via tutor_capacity=. Pass a real
# per-tutor dict once you have one (see real_excel_handler.
# load_tutor_info) rather than relying on this blanket default.
DEFAULT_TUTOR_CAPACITY = 2

# Optional. If you have a Lead/Returning/New roster for these tutors,
# pass it into match_real_choices(..., seniority_rank=your_dict) using
# these same values. Until then, every tutor is treated as equal
# seniority (the sheet itself has no seniority column to read from).
SENIORITY_RANK = {"Lead": 3, "Returning": 2, "New": 1}

# Classes in this tier are "Canvas Attached Only" by definition, so a
# tutor's "(CAT)" note is NOT a downside there (see the sheet's legend).
CAT_ONLY_TIER_LABEL = "CAT Only"


def is_cat_placement(class_record, tutor_name):
    """
    True when placing this tutor in this class means a Canvas-Attached-
    only placement that we'd rather avoid: the tutor wrote exactly
    "(CAT)" for the class, and the class isn't itself a CAT Only class
    (where every placement is Canvas Attached anyway).
    """
    return (
        class_record["tier_label"] != CAT_ONLY_TIER_LABEL
        and tutor_name in class_record.get("cat_candidates", ())
    )


def match_real_choices_bruteforce(
    classes, seniority_rank=None, tutor_capacity=None, show_trace=False
):
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
        6. Use as FEW "(CAT)" placements as possible: when a class can
           be filled equally well by a tutor who isn't Canvas-Attached-
           only for it, prefer that tutor. (Not applied to CAT Only
           classes, which are Canvas Attached by definition.)
        7. Among ties on all of the above, maximize total preference
           score (how good a choice tier each filled class was for its
           tutor).
        8. Among ties on all of the above, prefer giving good outcomes
           to more senior tutors (only if seniority_rank is supplied).

    A tutor can fill up to tutor_capacity[name] classes if given, or
    DEFAULT_TUTOR_CAPACITY otherwise. A class is only ever filled by one
    of its own actual candidates - never left empty by choice if a
    candidate is available AND filling it wouldn't require sacrificing
    a higher-priority class elsewhere.

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
    if tutor_capacity is None:
        tutor_capacity = {}

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

    def make_key(filled_by_priority, tutor_load, non_cat_count, total_score, total_seniority):
        employed_count = len(tutor_load)
        return (
            tuple(filled_by_priority[p] for p in priorities)
            + (employed_count, non_cat_count, total_score, total_seniority)
        )

    def upper_bound_key(index, filled_by_priority, tutor_load, non_cat_count, total_score):
        remaining_counts = remaining_by_priority_from[index]
        optimistic_filled = {
            p: filled_by_priority[p] + remaining_counts[p] for p in priorities
        }
        remaining_classes = len(ordered_classes) - index
        # Best case: every remaining class employs a brand-new tutor.
        optimistic_employed = len(tutor_load) + remaining_classes
        # Best case: every remaining class is filled without a CAT placement.
        optimistic_non_cat = non_cat_count + remaining_classes
        optimistic_score = total_score + PREFERENCE_SCORES[1] * remaining_classes
        # Seniority bound is left unbounded since it's a low-stakes
        # tie-breaker only.
        return tuple(optimistic_filled[p] for p in priorities) + (
            optimistic_employed,
            optimistic_non_cat,
            optimistic_score,
            float("inf"),
        )

    def backtrack(
        index, tutor_load, filled_by_priority, assignment,
        non_cat_count, total_score, total_seniority,
    ):
        if best["key"] is not None:
            bound = upper_bound_key(
                index, filled_by_priority, tutor_load, non_cat_count, total_score
            )
            if bound < best["key"]:
                return

        if index == len(ordered_classes):
            key = make_key(
                filled_by_priority, tutor_load, non_cat_count, total_score, total_seniority
            )
            if best["key"] is None or key > best["key"]:
                best["key"] = key
                best["assignment"] = dict(assignment)
            return

        class_record = ordered_classes[index]
        tier_priority = class_record["tier_priority"]

        for tutor_name, choice_tier in class_record["candidates"]:
            if tutor_load.get(tutor_name, 0) >= tutor_capacity.get(tutor_name, DEFAULT_TUTOR_CAPACITY):
                continue

            preference_points = PREFERENCE_SCORES[choice_tier]
            rank = seniority_rank.get(tutor_name, 0)
            cat_placement = is_cat_placement(class_record, tutor_name)

            tutor_load[tutor_name] = tutor_load.get(tutor_name, 0) + 1
            assignment[class_record["class_id"]] = (tutor_name, choice_tier)
            filled_by_priority[tier_priority] += 1

            if show_trace:
                print(
                    f"{class_record['class_id']} -> {tutor_name} "
                    f"(their choice {choice_tier}, tier {class_record['tier_label']}"
                    f"{', CAT' if cat_placement else ''})"
                )

            backtrack(
                index + 1,
                tutor_load,
                filled_by_priority,
                assignment,
                non_cat_count + (0 if cat_placement else 1),
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
            non_cat_count,
            total_score,
            total_seniority,
        )

    initial_filled = {p: 0 for p in priorities}
    backtrack(0, {}, initial_filled, {}, 0, 0, 0)

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
                    "CAT": False,
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
                    "CAT": is_cat_placement(class_record, tutor_name),
                }
            )

    results.sort(key=lambda r: r["Class"])

    return results, best["key"]


def match_real_choices_fast(classes, seniority_rank=None, tutor_capacity=None, tie_break_seed=None):
    """
    Same priority rules and output as match_real_choices_bruteforce,
    but solved EXACTLY via weighted bipartite matching
    (scipy.optimize.linear_sum_assignment) instead of brute-force
    search. Finds the true mathematical optimum, instantly, regardless
    of how many classes or tutors are involved.

    How the priority levels are enforced with a single matching call:
    each level (tier priority, then "every tutor gets used at least
    once", then "avoid (CAT) placements", then preference score, then
    seniority) gets its own "weight"
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

    tie_break_seed: optional. When two or more fully optimal
    assignments exist (the SAME tier fills, employed count, preference
    score, and seniority score, just different specific tutors on some
    classes), this normally returns whichever one the solver happens to
    land on first. Passing a seed here adds a microscopic amount of
    random noise (far too small to ever change a real decision) so a
    different seed can surface a genuinely different, equally-optimal
    assignment. See find_alternative_optimal_assignments, which uses
    this to discover every alternative worth showing a human.
    """
    import random as _random

    import numpy as np
    from scipy.optimize import linear_sum_assignment

    if seniority_rank is None:
        seniority_rank = {}
    if tutor_capacity is None:
        tutor_capacity = {}

    rng = _random.Random(tie_break_seed) if tie_break_seed is not None else None

    num_classes = len(classes)
    priorities = sorted(set(TIER_FILL_PRIORITY.values()) | {c["tier_priority"] for c in classes})

    tutor_names = sorted({name for c in classes for name, _ in c["candidates"]})
    num_tutors = len(tutor_names)

    # Weight for each level, built from the bottom up so every level
    # strictly dominates the MAXIMUM possible combined total of every
    # level beneath it. That makes "maximize total weight" identical to
    # comparing the levels one at a time, in order. Each bound uses the
    # real maximum for that level (e.g. at most num_tutors employed
    # tutors, at most n_p classes in a tier) rather than a loose
    # worst-case, which keeps every weight small enough that float64
    # arithmetic stays exact - important, because the lowest levels
    # (seniority, the random tie-break noise) are tiny numbers sitting
    # next to the huge top-tier weights.
    max_seniority_contribution = max(SENIORITY_RANK.values(), default=1) * max(PREFERENCE_SCORES.values())
    max_preference_contribution = max(PREFERENCE_SCORES.values())

    seniority_weight = 1
    seniority_max_total = max_seniority_contribution * num_classes * seniority_weight

    preference_weight = seniority_max_total + 1
    preference_max_total = max_preference_contribution * num_classes * preference_weight

    # "Avoid a CAT placement" is a bonus for every filled class that is
    # NOT a CAT placement. It must outweigh any total preference score.
    cat_weight = preference_max_total + seniority_max_total + 1
    cat_max_total = num_classes * cat_weight

    # "Employ a new tutor" must outweigh any total of the levels below.
    employment_weight = cat_max_total + preference_max_total + seniority_max_total + 1
    employment_max_total = num_tutors * employment_weight

    below_max = (
        employment_max_total + cat_max_total + preference_max_total + seniority_max_total
    )
    classes_in_priority = {p: 0 for p in priorities}
    for c in classes:
        classes_in_priority[c["tier_priority"]] += 1

    tier_weight = {}
    for p in reversed(priorities):  # build from LEAST urgent up to MOST urgent
        tier_weight[p] = below_max + 1
        below_max += classes_in_priority[p] * tier_weight[p]

    # Build the list of tutor "slots" - tutor_capacity[name] (or
    # DEFAULT_TUTOR_CAPACITY) interchangeable copies per tutor, each
    # tagged with which capacity slot (0-indexed) it is - so this
    # becomes an ordinary 1-to-1 assignment problem between classes and
    # slots, while still knowing which slot is a tutor's FIRST (the one
    # eligible for the employment bonus).
    slots = [
        (name, slot_number)
        for name in tutor_names
        for slot_number in range(tutor_capacity.get(name, DEFAULT_TUTOR_CAPACITY))
    ]
    num_slots = len(slots)

    # Float64 holds integers exactly up to 2**53. Fail loudly rather than
    # return a subtly wrong answer if a future, much larger sheet ever
    # pushes the top weight past that.
    if tier_weight[priorities[0]] * 2 >= 2 ** 53:
        raise ValueError("Problem too large for exact float64 weights.")

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
            non_cat_bonus = 0 if is_cat_placement(class_record, tutor_name) else cat_weight

            value = (
                tier_weight[class_record["tier_priority"]]
                + employment_bonus
                + non_cat_bonus
                + preference_points * preference_weight
                + (rank * preference_points) * seniority_weight
            )
            if rng is not None:
                # Microscopic noise (<< 1, the smallest real weight unit)
                # so it can only ever break an EXACT tie, never change
                # which outcome is actually better.
                value += rng.uniform(0, 0.5 / max(num_classes, 1))
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
    non_cat_count = 0

    for class_record in classes:
        entry = assignment.get(class_record["class_id"])
        if entry is None:
            results.append(
                {
                    "Class": class_record["class_id"],
                    "Tier": class_record["tier_label"],
                    "Assigned Tutor": None,
                    "Their Choice": None,
                    "CAT": False,
                }
            )
        else:
            tutor_name, choice_tier = entry
            preference_points = PREFERENCE_SCORES[choice_tier]
            cat_placement = is_cat_placement(class_record, tutor_name)
            filled_by_priority[class_record["tier_priority"]] += 1
            total_score += preference_points
            total_seniority += seniority_rank.get(tutor_name, 0) * preference_points
            if not cat_placement:
                non_cat_count += 1
            results.append(
                {
                    "Class": class_record["class_id"],
                    "Tier": class_record["tier_label"],
                    "Assigned Tutor": tutor_name,
                    "Their Choice": choice_tier,
                    "CAT": cat_placement,
                }
            )

    results.sort(key=lambda r: r["Class"])
    employed_count = len({r["Assigned Tutor"] for r in results if r["Assigned Tutor"]})
    key = (
        tuple(filled_by_priority[p] for p in priorities)
        + (employed_count, non_cat_count, total_score, total_seniority)
    )

    return results, key


def find_alternative_optimal_assignments(
    classes, seniority_rank=None, tutor_capacity=None, num_attempts=40, related_sections=None
):
    """
    Find every genuinely-tied-for-best tutor for each class, so a human
    can make the final call wherever more than one option is equally
    good - rather than silently picking whichever one the solver
    happened to land on.

    How it works: solve once with NO tie-break noise to get the true
    optimal key (the baseline). Then solve again many times, each with
    a different tiny random tie-break seed, which can shuffle WHICH
    tutor fills a contested class without ever changing the actual
    optimal key. Any run whose key doesn't exactly match the baseline
    is discarded (that run's noise accidentally mattered for some
    other reason, or is otherwise not trustworthy) - so everything kept
    is a CONFIRMED equally-optimal assignment, not a guess.

    related_sections: optional, from
    real_excel_handler.find_related_sections(file_path) - a dict of
    class_id -> group_id for classes that are likely the same course
    offering (e.g. a lecture and its lab). When a group's classes are
    ALL contested, and one of the confirmed-optimal alternatives has
    the SAME tutor covering the whole group, that combination is
    marked "recommended" - a low-stakes nudge toward keeping a lecture
    and its lab(s) with one tutor when it costs nothing, while still
    showing every other equally-valid option (including split ones,
    since sometimes only one tutor is available for the lab).

    Returns a list of dicts, one per class:
        {
            "Class": "PSY 300 E3L",
            "Tier": "Tier 1 EU",
            "is_contested": True,
            "options": [
                {"Assigned Tutor": "Elizabeth Lanovaya", "Their Choice": 2, "recommended": False},
                {"Assigned Tutor": "Cassidy Rosenbaum", "Their Choice": 1, "recommended": True},
            ],
        }
    "options" has exactly one entry for a class with no tie, and more
    than one for a class where multiple tutors are equally valid at the
    optimum - this is what a results page should show a dropdown for.

    This surfaces alternatives FOUND by the random attempts, which is a
    practical, honest approach - it is not a mathematical guarantee of
    finding every possible tied assignment if ties involve complex
    multi-class swap chains, but num_attempts=40 reliably surfaces the
    simple single and double swaps that make up the overwhelming
    majority of real ties. Increase num_attempts for more thoroughness
    at the cost of more runtime (each attempt is still well under a
    second).
    """
    if seniority_rank is None:
        seniority_rank = {}
    if related_sections is None:
        related_sections = {}

    baseline_results, baseline_key = match_real_choices_fast(classes, seniority_rank, tutor_capacity)

    options_by_class = {
        r["Class"]: {(r["Assigned Tutor"], r["Their Choice"])}
        for r in baseline_results
        if r["Assigned Tutor"] is not None
    }
    tier_by_class = {r["Class"]: r["Tier"] for r in baseline_results}
    unfilled_classes = {r["Class"] for r in baseline_results if r["Assigned Tutor"] is None}

    # Track, for each attempt that matches the baseline key, the full
    # tutor assigned to every class - needed to check whether a single
    # attempt kept a whole related-section group with one tutor.
    confirmed_assignments = [
        {r["Class"]: r["Assigned Tutor"] for r in baseline_results if r["Assigned Tutor"]}
    ]

    for seed in range(num_attempts):
        attempt_results, attempt_key = match_real_choices_fast(
            classes, seniority_rank, tutor_capacity, tie_break_seed=seed
        )

        if attempt_key != baseline_key:
            continue  # this run's noise changed something real - discard it

        confirmed_assignments.append(
            {r["Class"]: r["Assigned Tutor"] for r in attempt_results if r["Assigned Tutor"]}
        )

        for r in attempt_results:
            if r["Assigned Tutor"] is None:
                continue
            options_by_class.setdefault(r["Class"], set()).add(
                (r["Assigned Tutor"], r["Their Choice"])
            )

    # For each related-section group where every member is contested,
    # check whether any confirmed assignment kept the whole group with
    # one tutor - if so, that tutor's option is "recommended" there.
    group_to_classes = {}
    for class_id, group_id in related_sections.items():
        group_to_classes.setdefault(group_id, []).append(class_id)

    recommended_tutor_by_class = {}
    for group_id, group_class_ids in group_to_classes.items():
        relevant = [c for c in group_class_ids if c in options_by_class]
        if len(relevant) < 2:
            continue  # nothing to coordinate - only matters for groups of 2+

        for assignment in confirmed_assignments:
            tutors_in_group = {assignment.get(c) for c in relevant}
            if len(tutors_in_group) == 1 and None not in tutors_in_group:
                same_tutor = next(iter(tutors_in_group))
                for c in relevant:
                    recommended_tutor_by_class[c] = same_tutor
                break

    results = []
    for class_id in sorted(set(tier_by_class) | set(unfilled_classes)):
        if class_id in unfilled_classes and class_id not in options_by_class:
            results.append(
                {
                    "Class": class_id,
                    "Tier": tier_by_class[class_id],
                    "is_contested": False,
                    "options": [],
                }
            )
            continue

        recommended_tutor = recommended_tutor_by_class.get(class_id)
        options = [
            {
                "Assigned Tutor": tutor,
                "Their Choice": choice,
                "recommended": tutor == recommended_tutor,
            }
            for tutor, choice in sorted(options_by_class[class_id])
        ]
        results.append(
            {
                "Class": class_id,
                "Tier": tier_by_class[class_id],
                "is_contested": len(options) > 1,
                "options": options,
            }
        )

    return results


if __name__ == "__main__":
    import sys

    project_folder = Path(__file__).parent

    if len(sys.argv) > 1:
        file_path = Path(sys.argv[1])
    else:
        file_path = project_folder / "sample_data" / "real_choices_sample.xlsx"

    classes = load_real_choices(file_path)

    # Per-tutor Max Classes and Seniority from the "Tutors" sheet, if it
    # exists and has been filled in. Anything left blank uses defaults.
    capacities, seniority_labels = load_tutor_info(
        file_path, known_tutor_names=tutor_names_from_classes(classes)
    )
    seniority_rank = {name: SENIORITY_RANK[label] for name, label in seniority_labels.items()}
    print(
        f"Tutors sheet: {len(capacities)} Max Classes values and "
        f"{len(seniority_labels)} Seniority values loaded "
        f"(blank = default of {DEFAULT_TUTOR_CAPACITY} classes / no seniority tie-break)."
    )

    results, key = match_real_choices_fast(
        classes, seniority_rank=seniority_rank, tutor_capacity=capacities
    )

    filled = [r for r in results if r["Assigned Tutor"] is not None]
    unfilled = [r for r in results if r["Assigned Tutor"] is None]

    print(f"\n{len(filled)} of {len(results)} candidate-having classes filled\n")
    print("=" * 75)
    for r in filled:
        cat_tag = ", CAT" if r["CAT"] else ""
        print(
            f"{r['Class']} ({r['Tier']}) -> {r['Assigned Tutor']} "
            f"[their choice {r['Their Choice']}{cat_tag}]"
        )
    print("=" * 75)

    cat_placements = [r for r in filled if r["CAT"]]
    print(
        f"\n{len(cat_placements)} of {len(filled)} placements are Canvas-Attached-only "
        "((CAT) tutors in non-CAT-Only classes)."
    )
    for r in cat_placements:
        print(f"  {r['Class']} ({r['Tier']}) -> {r['Assigned Tutor']}")

    if unfilled:
        print(f"\n{len(unfilled)} classes could NOT be filled (not enough tutors):")
        for r in unfilled:
            print(f"  {r['Class']} ({r['Tier']})")