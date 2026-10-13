from itertools import permutations
from pathlib import Path

from excel_handler import load_excel_file


PREFERENCE_COLUMNS = [
    "First Choice",
    "Second Choice",
    "Third Choice",
]

PREFERENCE_SCORES = {
    0: 3,
    1: 2,
    2: 1,
}


def get_tutor_preferences(tutors):
    """Create a dictionary containing each tutor's preferences."""
    preferences = {}

    for _, tutor in tutors.iterrows():
        tutor_name = tutor["Tutor Name"]

        preferences[tutor_name] = [
            tutor["First Choice"],
            tutor["Second Choice"],
            tutor["Third Choice"],
        ]

    return preferences


def calculate_score(assignment, preferences):
    """
    Calculate an assignment's total preference score.

    Return None if a tutor is assigned outside their preferences.
    """
    total_score = 0

    for tutor_name, class_name in assignment.items():
        tutor_preferences = preferences[tutor_name]

        if class_name not in tutor_preferences:
            return None

        preference_index = tutor_preferences.index(class_name)
        total_score += PREFERENCE_SCORES[preference_index]

    return total_score


def find_optimal_assignments(tutors, classes):
    """Test every one-to-one assignment and find the highest score."""
    tutor_names = list(tutors["Tutor Name"])
    class_names = list(classes["Class Name"])
    preferences = get_tutor_preferences(tutors)

    best_score = -1
    best_assignments = []

    for class_order in permutations(class_names):
        assignment = dict(zip(tutor_names, class_order))
        score = calculate_score(assignment, preferences)

        # Skip assignments that violate tutor preferences.
        if score is None:
            continue

        if score > best_score:
            best_score = score
            best_assignments = [assignment]

        elif score == best_score:
            best_assignments.append(assignment)

    return best_score, best_assignments


if __name__ == "__main__":
    project_folder = Path(__file__).parent

    sample_file = (
        project_folder
        / "sample_data"
        / "sample_40_tutors.xlsx"
    )

    tutors_data, classes_data = load_excel_file(sample_file)

    proposed_assignment = {
        "Alice": "Chemistry",
        "Bob": "Biology",
        "Carl": "Calculus",
        "Denis": "Programming",
        "Eric": "Physics",
    }

    preferences = get_tutor_preferences(tutors_data)

    proposed_score = calculate_score(
        proposed_assignment,
        preferences,
    )

    best_score, best_assignments = find_optimal_assignments(
        tutors_data,
        classes_data,
    )

    print(f"Proposed assignment score: {proposed_score}")
    print(f"Optimal score: {best_score}")

    if proposed_score == best_score:
        print("The proposed assignment is preference-optimal.")
    else:
        print("The proposed assignment is not preference-optimal.")

    print(
        f"\nNumber of assignments with the optimal score: "
        f"{len(best_assignments)}"
    )

    for number, assignment in enumerate(
        best_assignments,
        start=1,
    ):
        print(f"\nOptimal assignment {number}:")

        for tutor_name, class_name in assignment.items():
            preference_number = (
                preferences[tutor_name].index(class_name) + 1
            )

            print(
                f"{tutor_name} -> {class_name} "
                f"[Choice {preference_number}]"
            )