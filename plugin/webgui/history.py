"""Bounded log-tail parsing for optional chat backfill, outside the main thread."""
from datetime import datetime
from pathlib import Path
import re
import time


def read_history(path, timestamp_format, limit, own_user, before):
    try:
        with Path(path).open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - 524288))
            raw = handle.read(524288).decode("utf-8", errors="replace")
        lines = raw.splitlines()
        if size > 524288:
            lines = lines[1:]
    except OSError:
        return []
    rows = []
    for line in lines[-limit:]:
        match = re.match(r"^(.*?)\[([^\]]+)\] (.*)$", line)
        if not match:
            continue
        prefix, user, message = match.groups()
        try:
            stamp = datetime.strptime(prefix.strip(), timestamp_format)
            if stamp.year == 1900:
                if not any(field in timestamp_format for field in ("%m", "%b", "%B", "%j")):
                    continue
                stamp = stamp.replace(year=datetime.now().year)
            timestamp = stamp.timestamp()
        except (ValueError, OverflowError):
            # Skip ambiguous formats rather than duplicate messages received live.
            continue
        if timestamp >= before:
            continue
        rows.append({"user": user, "message": message, "ts": timestamp, "outgoing": user == own_user,
                     "historical": True})
    return rows
