"""Local uploads, job result pages and file/ZIP downloads."""

from __future__ import annotations

from pathlib import Path

from flask import (
    Blueprint,
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

from ...core.exif import process_image_extract_and_embed
from ...core.filenames import safe_filename, unique_name
from ...core.jobs import (
    get_job_dir,
    is_image_file,
    iter_job_zip,
    list_job_files,
    new_job,
    resolve_job_file,
    staged_file,
)
from ...core.metadata_fields import load_user_exif_field_config
from ...settings import settings
from ..forms import parse_bool, parse_stem_suffix, sanitize_relative_path

bp = Blueprint("jobs", __name__)


def categorize_job_files(names: list[str]) -> dict[str, list[str]]:
    """Split output names into images, videos, JSON sidecars, and other."""
    groups: dict[str, list[str]] = {"images": [], "videos": [], "jsons": [], "others": []}
    for n in names:
        suf = Path(n).suffix.lower()
        if suf == ".json":
            groups["jsons"].append(n)
        elif suf in settings.SUPPORTED_FORMATS:
            groups["images"].append(n)
        elif suf in settings.VIDEO_FORMATS:
            groups["videos"].append(n)
        else:
            groups["others"].append(n)
    return groups


@bp.post("/upload")
def upload():
    wants_json = (
        "application/json" in (request.headers.get("Accept") or "").lower()
        and request.headers.get("X-Requested-With") == "XMLHttpRequest"
    )

    file_list = request.files.getlist("file")
    if not file_list:
        if wants_json:
            return jsonify({"ok": False, "detail": "No file was uploaded."}), 400
        flash("No file was uploaded. Try again.", "error")
        return redirect(url_for("home.index"))

    stem_suffix = parse_stem_suffix(request.form.get("stem_suffix"))
    include_json = parse_bool(request.form.get("include_json"))

    rows: list[tuple] = []
    form_rels = request.form.getlist("relative_paths")
    for i, f in enumerate(file_list):
        if not f.filename:
            continue
        rel = form_rels[i] if i < len(form_rels) else (f.filename or "")
        safe_rel = sanitize_relative_path(rel)
        if not safe_rel:  # path traversal or empty segments: keep the file, drop its folders
            safe_rel = safe_filename(rel.replace("\\", "/").rsplit("/", 1)[-1])
            if not safe_rel:
                continue
        name = Path(safe_rel).name
        if not is_image_file(Path(name)):
            continue
        rows.append((f, name, safe_rel))

    if not rows:
        if wants_json:
            return jsonify({"ok": False, "detail": "No supported images."}), 400
        flash("Choose at least one supported image (JPEG, PNG, etc.).", "error")
        return redirect(url_for("home.index"))

    job, job_out = new_job()
    job_out_res = job_out.resolve()
    field_config = load_user_exif_field_config(settings.metadata_preferences_path)

    processed = 0
    errors: list[str] = []
    out_payload: list[dict[str, str | None]] = []
    for i, (f, name, safe_rel) in enumerate(rows):
        out_subdir = job_out / Path(safe_rel).parent
        stem = Path(name).stem
        out_name = unique_name(out_subdir, safe_filename(f"{stem}{stem_suffix}{Path(name).suffix}"))
        with staged_file(job, i, name) as dest:
            f.save(dest)
            result = process_image_extract_and_embed(
                dest,
                out_subdir,
                field_config,
                stem_suffix="",
                output_stem=Path(out_name).stem,
                write_json=include_json,
            )
        if result.get("error"):
            errors.append(f"{safe_rel}: {result['error']}")
            continue
        processed += 1
        rel_img = Path(result["output_image"]).resolve().relative_to(job_out_res).as_posix()
        jp = result.get("json_path")
        rel_json = Path(jp).resolve().relative_to(job_out_res).as_posix() if jp else None
        out_payload.append(
            {
                "relative_path": rel_img,
                "json_relative_path": rel_json,
                "image_url": url_for("jobs.serve_file", job_id=job, filename=rel_img),
                "json_url": (
                    url_for("jobs.serve_file", job_id=job, filename=rel_json) if rel_json else None
                ),
            }
        )

    if processed == 0:
        if wants_json:
            detail = errors[0] if errors else "Processing failed."
            return jsonify({"ok": False, "processed": 0, "errors": errors, "detail": detail}), 400
        flash("Could not process any images. " + (errors[0] if errors else ""), "error")
        return redirect(url_for("home.index"))

    session["last_job"] = job
    if wants_json:
        return jsonify(
            {
                "ok": True,
                "job_id": job,
                "job_url": url_for("jobs.result", job_id=job),
                "processed": processed,
                "errors": errors,
                "files": out_payload,
            }
        )

    msg = f"Done. Saved metadata for {processed} image(s)."
    if errors:
        msg += f" {len(errors)} could not be saved."
    flash(msg, "success")
    return redirect(url_for("jobs.result", job_id=job))


@bp.get("/job/<job_id>")
def result(job_id: str):
    base = get_job_dir(job_id)
    if base is None:
        flash("Those files aren't available anymore. Start from the home page.", "error")
        return redirect(url_for("home.index"))
    names = list_job_files(base)
    groups = categorize_job_files(names)

    def _items(ns: list[str]) -> list[dict[str, str]]:
        return [{"name": n, "label": n} for n in ns]

    return render_template(
        "job.html",
        job_id=job_id,
        failed=max(request.args.get("failed", 0, type=int), 0),
        file_count=len(names),
        image_files=_items(groups["images"]),
        video_files=_items(groups["videos"]),
        json_files=_items(groups["jsons"]),
        other_files=_items(groups["others"]),
    )


@bp.get("/files/<job_id>/<path:filename>")
def serve_file(job_id: str, filename: str):
    base = get_job_dir(job_id)
    if base is None:
        return "Not found", 404
    path = resolve_job_file(base, filename)
    if path is None or not path.is_file():
        return "Not found", 404
    rel = path.relative_to(base.resolve()).as_posix()
    return send_from_directory(base, rel, as_attachment=True)


@bp.get("/job/<job_id>/download-all")
def download_zip(job_id: str):
    base = get_job_dir(job_id)
    if base is None:
        return "Not found", 404
    if not list_job_files(base):
        return "No files", 404
    # Streamed so the download starts at once, however large the job is.
    return Response(
        (chunk for chunk in iter_job_zip(base) if chunk),
        mimetype="application/zip",
        headers={"Content-Disposition": f'attachment; filename="hicpicnunc-{job_id[:8]}.zip"'},
    )
