"""Crash capture for the Android build.

On a phone there is no terminal. An unhandled exception kills the process and
the traceback goes to logcat, which needs a USB cable and adb to read - so the
app just closes and takes the reason with it.

The pure helpers live here, with no Kivy import, so they can be unit tested
without a display or a GL context. main.py wires them into a Kivy
ExceptionHandler.
"""

from __future__ import annotations

import os
import time
import traceback

LOG_NAME = 'crash.log'

# A traceback is kept whole, but one absurd line (a repr of a huge object, say)
# must not be handed to the UI: Kivy renders a Label as a single GPU texture,
# and an over-wide one silently fails to draw on mobile GPUs.
MAX_LINE = 400
MAX_REPORT = 20000


def crash_log_path(data_dir):
    """Where the crash log lives, or None if there is nowhere to put it."""
    if not data_dir:
        return None
    return os.path.join(data_dir, LOG_NAME)


def format_report(exc, context=''):
    """Render an exception as a readable report.

    Accepts an exception instance, an (type, value, tb) triple, or a string
    that has already been formatted.
    """
    if isinstance(exc, str):
        body = exc
    elif isinstance(exc, tuple) and len(exc) == 3:
        body = ''.join(traceback.format_exception(*exc))
    elif isinstance(exc, BaseException):
        body = ''.join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )
    else:
        body = str(exc)

    stamp = time.strftime('%Y-%m-%d %H:%M:%S')
    head = f"[{stamp}] {context}".strip()
    return f"{head}\n{body}".strip()


def clamp_report(report, max_line=MAX_LINE, max_report=MAX_REPORT):
    """Trim a report to something a Label can safely rasterise."""
    lines = []
    for line in report.splitlines():
        if len(line) > max_line:
            line = line[:max_line] + ' ...'
        lines.append(line)
    out = '\n'.join(lines)
    if len(out) > max_report:
        out = out[:max_report] + '\n... (truncated)'
    return out


def write_crash(data_dir, report):
    """Append a report to the crash log. Returns the path, or None.

    Never raises: it is called from an exception handler, and a failure to
    write must not become a second crash.
    """
    path = crash_log_path(data_dir)
    if not path:
        return None
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'a', encoding='utf-8') as fh:
            fh.write(report.rstrip() + '\n\n' + ('-' * 60) + '\n\n')
        return path
    except Exception:
        return None


def read_crash(data_dir):
    """Return the crash log's contents, or '' if there is none."""
    path = crash_log_path(data_dir)
    if not path:
        return ''
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            return fh.read()
    except Exception:
        return ''


def clear_crash(data_dir):
    """Delete the crash log. Returns True if a file was removed."""
    path = crash_log_path(data_dir)
    if not path:
        return False
    try:
        os.remove(path)
        return True
    except Exception:
        return False
