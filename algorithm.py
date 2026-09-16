from collections import deque
from pathlib import Path

from excel_handler import load_excel_file


SENIORITY_RANK = {
    "Lead": 3,
    "Returning": 2,
    "New": 1,
}

PREFERENCE_COLUMNS = [
    "First Choice",
    "Second Choice",
    "Third Choice",
]


def validate_algorithm_input(tutors, classes):
    """Validate the data required by the one-to-one algorithm."""

    if len(tutors) != len(classes):
        raise ValueError(
            "The one-to-one algorithm requires the same number "
            "of tutors and classes."
        )

    if tutors["Tutor Name"].duplicated().any():
        duplicate_names = tutors.loc[
            tutors["Tutor Name"].duplicated(keep=False),
            "Tutor Name",
        ].tolist()

        raise ValueError(
            f"Tutor names must be unique. Duplicates: {duplicate_names}"
        )

    if classes["Class Name"].duplicated().any():
        duplicate_classes = classes.loc[
            classes["Class Name"].duplicated(keep=False),
            "Class Name",
        ].tolist()

        raise ValueError(
            f"Class names must be unique. Duplicates: {duplicate_classes}"
        )

    valid_classes = set(classes["Class Name"])

    for _, tutor in tutors.iterrows():
        tutor_name = tutor["Tutor Name"]
        seniority = tutor["Seniority"]

        if seniority not in SENIORITY_RANK:
            raise ValueError(
                f"{tutor_name} has invalid seniority: {seniority}"
            )

        preferences = [
            tutor[column]
            for column in PREFERENCE_COLUMNS
        ]

        if len(set(preferences)) != len(preferences):
            raise ValueError(
                f"{tutor_name} has duplicate class preferences."
            )

        invalid_choices = [
            choice
            for choice in preferences
            if choice not in valid_classes
        ]

        if invalid_choices:
            raise ValueError(
                f"{tutor_name} selected classes that do not exist: "
                f"{invalid_choices}"
            )


def class_prefers_new_tutor(
    new_tutor,
    current_tutor,
    tutor_data,
    next_proposal,
):
    """
    Determine whether a class should accept the new tutor.

    Priority:
    1. Tutor with fewer remaining scheduling options
    2. Tutor with higher seniority
    3. Current tutor remains when both are equal
    """
    new_remaining_options = (
        len(tutor_data[new_tutor]["Preferences"])
        - next_proposal[new_tutor]
    )

    current_remaining_options = (
        len(tutor_data[current_tutor]["Preferences"])
        - next_proposal[current_tutor]
    )

    # A tutor with fewer remaining choices has greater urgency.
    if new_remaining_options != current_remaining_options:
        return new_remaining_options < current_remaining_options

    # If urgency is equal, compare seniority.
    new_seniority = tutor_data[new_tutor]["Seniority"]
    current_seniority = tutor_data[current_tutor]["Seniority"]

    new_rank = SENIORITY_RANK[new_seniority]
    current_rank = SENIORITY_RANK[current_seniority]

    if new_rank != current_rank:
        return new_rank > current_rank

    # If both factors are equal, keep the current tutor.
    return False


def gale_shapley(tutors, classes, show_trace=False):
    """
    Match tutors and classes using modified one-to-one Gale-Shapley.

    Tutors propose in preference order. Classes consider remaining
    options first and seniority second.
    """
    validate_algorithm_input(tutors, classes)

    tutor_data = {}

    for _, tutor in tutors.iterrows():
        tutor_name = tutor["Tutor Name"]

        tutor_data[tutor_name] = {
            "Seniority": tutor["Seniority"],
            "Preferences": [
                tutor["First Choice"],
                tutor["Second Choice"],
                tutor["Third Choice"],
            ],
        }

    class_names = list(classes["Class Name"])

    class_matches = {
        class_name: None
        for class_name in class_names
    }

    tutor_matches = {
        tutor_name: None
        for tutor_name in tutor_data
    }

    next_proposal = {
        tutor_name: 0
        for tutor_name in tutor_data
    }

    free_tutors = deque(tutor_data.keys())

    if show_trace:
        print("\nProposal Trace")
        print("=" * 75)

    while free_tutors:
        tutor_name = free_tutors.popleft()
        preferences = tutor_data[tutor_name]["Preferences"]
        preference_index = next_proposal[tutor_name]

        if preference_index >= len(preferences):
            if show_trace:
                print(
                    f"{tutor_name} has exhausted all preferences."
                )
            continue

        proposed_class = preferences[preference_index]

        if show_trace:
            print(
                f"\n{tutor_name} proposes to {proposed_class} "
                f"(choice {preference_index + 1})."
            )

        next_proposal[tutor_name] += 1
        current_tutor = class_matches[proposed_class]

        if current_tutor is None:
            class_matches[proposed_class] = tutor_name
            tutor_matches[tutor_name] = proposed_class

            if show_trace:
                print(
                    f"  {proposed_class} is available and "
                    f"accepts {tutor_name}."
                )

            continue

        new_remaining = (
            len(tutor_data[tutor_name]["Preferences"])
            - next_proposal[tutor_name]
        )

        current_remaining = (
            len(tutor_data[current_tutor]["Preferences"])
            - next_proposal[current_tutor]
        )

        if show_trace:
            print(
                f"  {proposed_class} currently has "
                f"{current_tutor}."
            )
            print(
                f"  {tutor_name}: "
                f"{new_remaining} untried choices, "
                f"{tutor_data[tutor_name]['Seniority']}."
            )
            print(
                f"  {current_tutor}: "
                f"{current_remaining} untried choices, "
                f"{tutor_data[current_tutor]['Seniority']}."
            )

        if class_prefers_new_tutor(
            tutor_name,
            current_tutor,
            tutor_data,
            next_proposal,
        ):
            class_matches[proposed_class] = tutor_name
            tutor_matches[tutor_name] = proposed_class

            tutor_matches[current_tutor] = None
            free_tutors.append(current_tutor)

            if show_trace:
                print(
                    f"  {proposed_class} accepts {tutor_name} "
                    f"and rejects {current_tutor}."
                )

        else:
            free_tutors.append(tutor_name)

            if show_trace:
                print(
                    f"  {proposed_class} keeps {current_tutor} "
                    f"and rejects {tutor_name}."
                )

    if show_trace:
        print("\n" + "=" * 75)
        print("Proposal process complete.")

    unmatched_tutors = [
        tutor_name
        for tutor_name, class_name in tutor_matches.items()
        if class_name is None
    ]

    unfilled_classes = [
        class_name
        for class_name, tutor_name in class_matches.items()
        if tutor_name is None
    ]

    if unmatched_tutors or unfilled_classes:
        raise ValueError(
            "A complete one-to-one matching was not possible. "
            f"Unmatched tutors: {unmatched_tutors}. "
            f"Unfilled classes: {unfilled_classes}."
        )

    results = []

    for tutor_name, class_name in tutor_matches.items():
        tutor = tutor_data[tutor_name]

        preference_number = (
            tutor["Preferences"].index(class_name) + 1
        )

        results.append(
            {
                "Tutor Name": tutor_name,
                "Seniority": tutor["Seniority"],
                "Assigned Class": class_name,
                "Preference Number": preference_number,
            }
        )

    results.sort(key=lambda result: result["Tutor Name"])

    return results


if __name__ == "__main__":
    project_folder = Path(__file__).parent

    sample_file = (
        project_folder
        / "sample_data"
        / "sample.xlsx"
    )

    try:
        tutors_data, classes_data = load_excel_file(sample_file)

        assignments = gale_shapley(
            tutors_data,
            classes_data,
        )

        print("\nGale-Shapley Tutor Assignments")
        print("=" * 75)

        for assignment in assignments:
            print(
                f"{assignment['Tutor Name']} "
                f"({assignment['Seniority']}) -> "
                f"{assignment['Assigned Class']} "
                f"[Choice {assignment['Preference Number']}]"
            )

        print("=" * 75)
        print(f"Total assignments: {len(assignments)}")

    except (FileNotFoundError, ValueError, KeyError) as error:
        print(f"Error: {error}")