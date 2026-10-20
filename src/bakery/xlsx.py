"""Byte-reproducible .xlsx output.

openpyxl's `Workbook.save` stamps the current time into docProps/core.xml and
every zip entry carries the current time, so two saves of the same workbook
differ. Generated files are compared byte-for-byte (determinism tests,
committed mock data), so we pin both.
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.writer.excel import ExcelWriter

_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


def workbook_bytes(wb: Workbook, timestamp: datetime) -> bytes:
    """Serialize `wb` with `timestamp` as created/modified and fixed zip entry times."""
    wb.properties.creator = "bakery-orders"
    wb.properties.created = timestamp
    wb.properties.modified = timestamp
    raw = io.BytesIO()
    # ExcelWriter directly: Workbook.save would overwrite `modified` with now().
    ExcelWriter(wb, zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED, allowZip64=True)).save()
    out = io.BytesIO()
    with zipfile.ZipFile(raw) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            pinned = zipfile.ZipInfo(info.filename, date_time=_ZIP_EPOCH)
            pinned.compress_type = zipfile.ZIP_DEFLATED
            pinned.external_attr = info.external_attr
            dst.writestr(pinned, src.read(info.filename))
    return out.getvalue()


def save_workbook(wb: Workbook, path: Path, timestamp: datetime) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(workbook_bytes(wb, timestamp))
    return path
