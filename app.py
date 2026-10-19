import time
from pathlib import Path
from uuid import uuid4

from flask import Flask, jsonify, render_template, request, send_file

from exporter import build_workbook, validate_export_request
from io import BytesIO
from placement_service import run_placement


app = Flask(__name__)

PROJECT_FOLDER = Path(__file__).parent
UPLOAD_FOLDER = PROJECT_FOLDER / "uploads"

UPLOAD_FOLDER.mkdir(exist_ok=True)

# Uploads are deleted right after each run. This is a safety net for the
# rare case where the app was stopped mid-run and left a file behind.
STALE_UPLOAD_SECONDS = 5 * 60


def remove_stale_uploads(max_age_seconds=STALE_UPLOAD_SECONDS):
    """Delete leftover uploaded workbooks older than max_age_seconds.

    Only files this app created (32-hex-character name + .xlsx) are touched,
    and a run only takes a moment, so a file this old can't be in use.
    """
    now = time.time()
    for path in UPLOAD_FOLDER.glob("*.xlsx"):
        stem = path.stem
        if len(stem) != 32 or any(ch not in "0123456789abcdef" for ch in stem):
            continue
        try:
            if now - path.stat().st_mtime > max_age_seconds:
                path.unlink()
        except OSError:
            pass  # already gone, or in use - try again next time


remove_stale_uploads()

app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

ALLOWED_EXTENSIONS = {".xlsx"}


def is_allowed_file(filename):
    """Return True when the uploaded file is an Excel workbook."""
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


@app.route("/")
def index():
    """Display the Excel upload page."""
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload_file():
    """Receive an Excel file, run the placement algorithm, show the result."""
    if "excel_file" not in request.files:
        return render_template("index.html", error="No file was included in the request."), 400

    uploaded_file = request.files["excel_file"]

    if uploaded_file.filename == "":
        return render_template("index.html", error="Please select an Excel file."), 400

    if not is_allowed_file(uploaded_file.filename):
        return render_template("index.html", error="Only .xlsx files are accepted."), 400

    remove_stale_uploads()

    # A random name avoids clashes between two people uploading at once.
    saved_path = UPLOAD_FOLDER / f"{uuid4().hex}.xlsx"

    try:
        uploaded_file.save(saved_path)
        result = run_placement(saved_path)

        return render_template(
            "results.html",
            filename=uploaded_file.filename,
            result=result,
        )

    except (ValueError, KeyError) as error:
        message = str(error)
        if "Excel file format" in message or "File is not a zip" in message:
            message = "That file could not be opened as an Excel workbook (.xlsx)."
        return render_template("index.html", error=message), 400

    except Exception:
        app.logger.exception("Placement run failed")
        return render_template(
            "index.html",
            error=(
                "Something went wrong while reading or matching that file. "
                "Please check that it is the placement workbook with a "
                "'Choices Round 1' sheet."
            ),
        ), 500

    finally:
        if saved_path.exists():
            saved_path.unlink()


@app.route("/export", methods=["POST"])
def export_results():
    """Turn the assignments currently on screen (including any edits the
    user made) into a downloadable Excel file."""
    try:
        cleaned = validate_export_request(request.get_json(silent=True))
    except ValueError as error:
        return jsonify(error=str(error)), 400

    return send_file(
        BytesIO(build_workbook(cleaned)),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="tutor_placements.xlsx",
    )


@app.errorhandler(413)
def file_too_large(error):
    """Handle files larger than the configured limit."""
    return render_template(
        "index.html", error="The uploaded file is too large. Maximum size: 10 MB."
    ), 413


if __name__ == "__main__":
    app.run(debug=True)