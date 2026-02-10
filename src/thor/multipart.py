"""
Multipart form-data parser for Thor framework.

Provides ``UploadFile`` for individual file uploads and
``parse_multipart`` to decode ``multipart/form-data`` request bodies.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any


@dataclass
class UploadFile:
    """
    Represents a single uploaded file from a multipart request.

    Attributes:
        filename: Original filename from the client.
        content_type: MIME type declared by the client (default
            ``application/octet-stream``).
        headers: Raw headers for this part.
        file: In-memory bytes buffer containing the upload contents.
    """

    filename: str
    content_type: str = "application/octet-stream"
    headers: dict[str, str] = field(default_factory=dict)
    file: io.BytesIO = field(default_factory=io.BytesIO, repr=False)

    # ------------------------------------------------------------------
    # Convenience API
    # ------------------------------------------------------------------

    async def read(self, size: int = -1) -> bytes:
        """Read file contents (async-compatible wrapper)."""
        return self.file.read(size)

    async def seek(self, offset: int) -> None:
        self.file.seek(offset)

    @property
    def size(self) -> int:
        """Total size of the upload in bytes."""
        pos = self.file.tell()
        self.file.seek(0, 2)
        length = self.file.tell()
        self.file.seek(pos)
        return length

    def close(self) -> None:
        self.file.close()

    def __del__(self) -> None:
        try:
            self.file.close()
        except Exception:
            pass


# -----------------------------------------------------------------------
# Parser
# -----------------------------------------------------------------------


def _parse_content_disposition(header: str) -> dict[str, str]:
    """Parse a ``Content-Disposition`` header into key/value pairs."""
    params: dict[str, str] = {}
    # The first token is the type (e.g. "form-data")
    parts = header.split(";")
    for part in parts[1:]:
        part = part.strip()
        if "=" not in part:
            continue
        key, _, val = part.partition("=")
        key = key.strip()
        val = val.strip().strip('"')
        params[key] = val
    return params


def parse_multipart(
    body: bytes,
    boundary: str,
) -> tuple[dict[str, str | list[str]], list[UploadFile]]:
    """
    Parse a ``multipart/form-data`` body.

    Returns a tuple of ``(form_fields, files)`` where *form_fields*
    is a dict of non-file field values and *files* is a list of
    :class:`UploadFile` instances.

    Parameters:
        body: Raw request body bytes.
        boundary: The multipart boundary string (from the
            ``Content-Type`` header).
    """
    form_fields: dict[str, str | list[str]] = {}
    files: list[UploadFile] = []

    # Boundaries are prefixed with "--" in the body
    delimiter = f"--{boundary}".encode()
    end_delimiter = f"--{boundary}--".encode()

    # Split on the boundary
    parts = body.split(delimiter)

    for part in parts:
        # Skip the preamble and the closing delimiter
        stripped = part.strip(b"\r\n")
        if not stripped or stripped == b"--" or stripped.startswith(end_delimiter):
            continue

        # Separate headers from body (double CRLF)
        header_end = part.find(b"\r\n\r\n")
        if header_end == -1:
            continue

        raw_headers = part[:header_end]
        part_body = part[header_end + 4 :]
        # Trim trailing \r\n
        if part_body.endswith(b"\r\n"):
            part_body = part_body[:-2]

        # Parse part headers
        part_headers: dict[str, str] = {}
        for line in raw_headers.split(b"\r\n"):
            line_str = line.decode("utf-8", errors="replace").strip()
            if ":" in line_str:
                hname, _, hval = line_str.partition(":")
                part_headers[hname.strip().lower()] = hval.strip()

        disposition = part_headers.get("content-disposition", "")
        disp_params = _parse_content_disposition(disposition)
        field_name = disp_params.get("name", "")

        if "filename" in disp_params:
            # File upload
            ct = part_headers.get("content-type", "application/octet-stream")
            buf = io.BytesIO(part_body)
            upload = UploadFile(
                filename=disp_params["filename"],
                content_type=ct,
                headers=part_headers,
                file=buf,
            )
            files.append(upload)
        else:
            # Regular form field
            value = part_body.decode("utf-8", errors="replace")
            existing = form_fields.get(field_name)
            if existing is None:
                form_fields[field_name] = value
            elif isinstance(existing, list):
                existing.append(value)
            else:
                form_fields[field_name] = [existing, value]

    return form_fields, files
