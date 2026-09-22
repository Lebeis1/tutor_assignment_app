from pathlib import Path

from algorithm import brute_force_match
from verify import get_tutor_preferences, find_optimal_assignments
from excel_handler import load_excel_file


def run_tests(sample_file):
    tutors, classes = load_excel_file(sample_file)

    # Run the real algorithm your app will ship with.
    assignments, algorithm_score = brute_force_match(tutors, classes)
    algorithm_assignment = {
        result["Tutor Name"]: result["Assigned Class"] for result in assignments
    }

    # Run a second, independently-written brute-force search as a cross-check.
    # It works differently (tries every permutation of ALL classes, then
    # throws out any that break someone's preferences), so agreement between
    # the two is strong evidence both are correct rather than both sharing
    # the same bug.
    verify_best_score, verify_best_assignments = find_optimal_assignments(
        tutors, classes
    )

    print("=== Cross-checking algorithm.py against verify.py ===\n")

    print(f"algorithm.py score:        {algorithm_score}")
    print(f"verify.py optimal score:   {verify_best_score}")
    score_matches = algorithm_score == verify_best_score
    print(f"Scores match:              {score_matches}")

    assignment_is_optimal = algorithm_assignment in verify_best_assignments
    print(f"Assignment is optimal:     {assignment_is_optimal}")

    preferences = get_tutor_preferences(tutors)
    only_uses_preferences = all(
        assigned_class in preferences[tutor_name]
        for tutor_name, assigned_class in algorithm_assignment.items()
    )
    print(f"Only used real choices:    {only_uses_preferences}")

    every_tutor_assigned = set(algorithm_assignment) == set(tutors["Tutor Name"])
    every_class_filled = set(algorithm_assignment.values()) == set(
        classes["Class Name"]
    )
    print(f"Every tutor assigned:      {every_tutor_assigned}")
    print(f"Every class filled:        {every_class_filled}")

    print("\nFinal assignment:")
    for tutor_name, assigned_class in sorted(algorithm_assignment.items()):
        choice_number = preferences[tutor_name].index(assigned_class) + 1
        print(f"  {tutor_name} -> {assigned_class} [Choice {choice_number}]")

    passed = all(
        [
            score_matches,
            assignment_is_optimal,
            only_uses_preferences,
            every_tutor_assigned,
            every_class_filled,
        ]
    )

    print("\nPASS" if passed else "\nFAIL")
    return passed


if __name__ == "__main__":
    project_folder = Path(__file__).parent
    sample_file = project_folder / "sample_data" / "sample.xlsx"
    run_tests(sample_file)