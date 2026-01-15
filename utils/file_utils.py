import base64
import os
import uuid
import mimetypes
from config import UPLOAD_FOLDER, UPLOAD_SUBDIRS

def _safe_filename_part(value: str) -> str:
    if value is None:
        return "NA"
    s = str(value).strip().replace(" ", "_")
    # remove characters that are not allowed in filenames (Windows-safe)
    for ch in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
        s = s.replace(ch, "")
    return s or "NA"


def save_base64_file(base64_string, subfolder, filename=None):
    """
    Save a base64 file to disk and return the filename.

    Args:
        base64_string: "data:<mime>;base64,...."
        subfolder: can be either:
                  - a key of UPLOAD_SUBDIRS (e.g. "PROJECT_PPRT", "TASK_FILES")
                  - or a direct folder name
        filename: optional custom filename WITHOUT extension
                 extension will be auto-detected from base64 header

    Returns:
        final saved filename with extension
    """
    if not base64_string:
        return None

    if "," not in base64_string:
        raise ValueError("Invalid base64 format")

    header, encoded = base64_string.split(",", 1)

    # Extract MIME type
    try:
        mime_type = header.split(";")[0].split(":")[1]
    except IndexError:
        raise ValueError("Invalid base64 header")

    # Guess file extension from MIME type
    extension = mimetypes.guess_extension(mime_type) or ".bin"

    # Decode Base64
    file_bytes = base64.b64decode(encoded)

    # ✅ Use custom filename if provided, else generate uuid
    if filename:
        base_name = _safe_filename_part(filename)
    else:
        base_name = str(uuid.uuid4())

    final_filename = f"{base_name}{extension}"

    # Folder path (same logic as your existing code)
    folder = os.path.join(
        UPLOAD_FOLDER,
        UPLOAD_SUBDIRS.get(subfolder, subfolder)
    )
    os.makedirs(folder, exist_ok=True)

    file_path = os.path.join(folder, final_filename)

    # Save file
    with open(file_path, "wb") as f:
        f.write(file_bytes)

    return final_filename
