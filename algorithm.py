from pathlib import Path

from excel_handler import load_excel_file


PREFERENCE_COLUMNS = ["First Choice", "Second Choice", "Third Choice"]

# Points awarded for landing a tutor on their Nth choice.
# Index 0 -> first choice, index 1 -> second choice, index 2 -> third choice.
PREFERENCE_SCORES = [3, 2, 1]

# Used ONLY to break ties between complete assignments that already have
# the exact same total preference score. Seniority can never cause a
# lower-scoring assignment to be chosen over a higher-scoring one.
SENIORITY_RANK = {
    "Lead": 3,
    "Returning": 2,
    "New": 1,
}


def validate_algorithm_input(tutors, classes):
    """Validate the data required by the brute-force algorithm."""

    if len(tutors) != len(classes):
        raise ValueError(
            "This algorithm requires the same number of tutors and classes, "
            "since every class must end up filled and every tutor assigned."
        )

    if tutors["Tutor Name"].duplicated().any():
        duplicate_names = tutors.loc[
            tutors["Tutor Name"].duplicated(keep=False), "Tutor Name"
        ].tolist()
        raise ValueError(f"Tutor names must be unique. Duplicates: {duplicate_names}")

    if classes["Class Name"].duplicated().any():
        duplicate_classes = classes.loc[
            classes["Class Name"].duplicated(keep=False), "Class Name"
        ].tolist()
        raise ValueError(f"Class names must be unique. Duplicates: {duplicate_classes}")

    valid_classes = set(classes["Class Name"])

    for _, tutor in tutors.iterrows():
        tutor_name = tutor["Tutor Name"]
        seniority = tutor["Seniority"]

        if seniority not in SENIORITY_RANK:
            raise ValueError(
                f"{tutor_name} has an unrecognized seniority: {seniority!r}. "
                f"Expected one of: {list(SENIORITY_RANK)}."
            )

        preferences = [tutor[column] for column in PREFERENCE_COLUMNS]

        if len(set(preferences)) != len(preferences):
            raise ValueError(f"{tutor_name} has duplicate class preferences.")

        invalid_choices = [
            choice for choice in preferences if choice not in valid_classes
        ]

        if invalid_choices:
            raise ValueError(
                f"{tutor_name} selected classes that do not exist: {invalid_choices}"
            )


def brute_force_match(tutors, classes, show_trace=False):
    """
    Find the complete tutor-to-class assignment with the highest total
    preference score, using ONLY each tutor's own top-3 choices.

    Every tutor ends up assigned and every class ends up filled. A tutor
    is never placed in a class they did not choose — if giving one
    tutor their preferred choice would force a conflict, the algorithm
    instead tries giving that tutor a lower choice so everyone can be
    placed, and keeps whichever complete combination scores highest
    overall.

    Seniority is a tie-breaker ONLY. If two or more complete assignments
    tie for the highest possible preference score, the one where more
    senior tutors landed on their better choices wins. Seniority never
    outweighs preference score — a Lead tutor cannot bump a New tutor
    out of a better assignment unless the total score stays exactly
    the same either way.

    This is a brute-force/backtracking search: for each tutor, in turn,
    it tries "assign to choice 1", "assign to choice 2", "assign to
    choice 3" (whichever are still available), recursing into every
    combination and remembering the best result seen so far. The
    branching factor per tutor is at most 3, so this stays far cheaper
    than trying every permutation of every class, and comfortably
    handles the class sizes an MVP like this targets.
    """
    validate_algorithm_input(tutors, classes)

    tutor_names = list(tutors["Tutor Name"])

    tutor_preferences = {
        tutor["Tutor Name"]: [tutor[column] for column in PREFERENCE_COLUMNS]
        for _, tutor in tutors.iterrows()
    }

    tutor_seniority_rank = {
        tutor["Tutor Name"]: SENIORITY_RANK[tutor["Seniority"]]
        for _, tutor in tutors.iterrows()
    }

    # best["key"] is (total_preference_score, total_seniority_score).
    # Python compares tuples left-to-right, so preference score always
    # decides first, and seniority only breaks an exact tie on it.
    best = {"key": (-1, -1), "assignment": None}

    def backtrack(
        index,
        used_classes,
        current_assignment,
        current_score,
        current_seniority_score,
    ):
        if index == len(tutor_names):
            current_key = (current_score, current_seniority_score)

            if current_key > best["key"]:
                best["key"] = current_key
                best["assignment"] = dict(current_assignment)

            return

        tutor_name = tutor_names[index]
        preferences = tutor_preferences[tutor_name]
        seniority_rank = tutor_seniority_rank[tutor_name]

        for choice_index, class_name in enumerate(preferences):
            if class_name in used_classes:
                continue

            used_classes.add(class_name)
            current_assignment[tutor_name] = class_name

            if show_trace:
                print(f"{tutor_name} -> {class_name} (choice {choice_index + 1})")

            preference_points = PREFERENCE_SCORES[choice_index]

            backtrack(
                index + 1,
                used_classes,
                current_assignment,
                current_score + preference_points,
                current_seniority_score + seniority_rank * preference_points,
            )

            used_classes.remove(class_name)
            del current_assignment[tutor_name]

    backtrack(0, set(), {}, 0, 0)

    if best["assignment"] is None:
        all_preferences = {
            class_name
            for preferences in tutor_preferences.values()
            for class_name in preferences
        }

        unwanted_classes = [
            class_name
            for class_name in classes["Class Name"]
            if class_name not in all_preferences
        ]

        if unwanted_classes:
            raise ValueError(
                "No complete assignment is possible because these classes "
                f"were not chosen by any tutor: {unwanted_classes}. "
                "Every class needs at least one tutor who listed it as a "
                "choice, or it can never be filled."
            )

        raise ValueError(
            "No complete assignment is possible using only tutors' top-3 "
            "choices. Check for classes that too few tutors selected "
            "relative to how many other tutors are competing for them."
        )

    results = []

    for tutor_name, assigned_class in best["assignment"].items():
        preference_number = (
            tutor_preferences[tutor_name].index(assigned_class) + 1
        )

        results.append(
            {
                "Tutor Name": tutor_name,
                "Assigned Class": assigned_class,
                "Preference Number": preference_number,
            }
        )

    results.sort(key=lambda result: result["Tutor Name"])

    total_preference_score, _ = best["key"]

    return results, total_preference_score


if __name__ == "__main__":
    project_folder = Path(__file__).parent

    sample_file = project_folder / "sample_data" / "sample.xlsx"

    try:
        tutors_data, classes_data = load_excel_file(sample_file)

        assignments, total_score = brute_force_match(tutors_data, classes_data)

        print("\nBrute-Force Tutor Assignments")
        print("=" * 75)

        for assignment in assignments:
            print(
                f"{assignment['Tutor Name']} -> "
                f"{assignment['Assigned Class']} "
                f"[Choice {assignment['Preference Number']}]"
            )

        print("=" * 75)
        print(f"Total assignments: {len(assignments)}")
        print(f"Total preference score: {total_score}")

    except (FileNotFoundError, ValueError, KeyError) as error:
        print(f"Error: {error}")