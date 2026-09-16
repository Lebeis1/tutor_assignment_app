from pathlib import Path

from flask import Flask, render_template, request
from werkzeug.utils import secure_filename

from excel_handler import load_excel_file


app = Flask(__name__)

PROJECT_FOLDER = Path(__file__).parent
UPLOAD_FOLDER = PROJECT_FOLDER / "uploads"

UPLOAD_FOLDER.mkdir(exist_ok=True)

app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

ALLOWED_EXTENSIONS = {".xlsx"}


def is_allowed_file(filename):
    """Return True when the uploaded file is an Excel workbook."""
    extension = Path(filename).suffix.lower()
    return extension in ALLOWED_EXTENSIONS


@app.route("/")
def index():
    """Display the Excel upload page."""
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload_file():
    """Receive, validate, and preview an uploaded Excel file."""
    if "excel_file" not in request.files:
        return render_template(
            "index.html",
            error="No file was included in the request.",
        )

    uploaded_file = request.files["excel_file"]

    if uploaded_file.filename == "":
        return render_template(
            "index.html",
            error="Please select an Excel file.",
        )

    if not is_allowed_file(uploaded_file.filename):
        return render_template(
            "index.html",
            error="Only .xlsx files are accepted.",
        )

    safe_filename = secure_filename(uploaded_file.filename)
    saved_path = UPLOAD_FOLDER / safe_filename

    try:
        uploaded_file.save(saved_path)

        tutors, classes = load_excel_file(saved_path)

        tutor_records = tutors.to_dict(orient="records")
        class_records = classes.to_dict(orient="records")

        return render_template(
            "results.html",
            filename=safe_filename,
            tutors=tutor_records,
            classes=class_records,
        )

    except (ValueError, KeyError) as error:
        return render_template(
            "index.html",
            error=str(error),
        )

    finally:
        if saved_path.exists():
            saved_path.unlink()


@app.errorhandler(413)
def file_too_large(error):
    """Handle files larger than the configured limit."""
    return render_template(
        "index.html",
        error="The uploaded file is too large. Maximum size: 5 MB.",
    ), 413


if __name__ == "__main__":
    app.run(debug=True)