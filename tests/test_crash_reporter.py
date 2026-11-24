"""Unit tests for crash_reporter - no Kivy, no display needed."""

import os
import tempfile

import crash_reporter as cr


def test_crash_log_path_joins_data_dir():
    assert cr.crash_log_path('/data/app') == os.path.join('/data/app', 'crash.log')


def test_crash_log_path_without_dir_is_none():
    assert cr.crash_log_path(None) is None
    assert cr.crash_log_path('') is None


def test_format_report_from_exception_includes_type_and_message():
    try:
        raise ValueError('boom')
    except ValueError as e:
        report = cr.format_report(e, 'While testing')
    assert 'ValueError' in report
    assert 'boom' in report
    assert 'While testing' in report
    assert report.startswith('[')          # timestamped


def test_format_report_accepts_a_plain_string():
    report = cr.format_report('already formatted', 'ctx')
    assert 'already formatted' in report
    assert 'ctx' in report


def test_format_report_includes_traceback_frames():
    def inner():
        raise RuntimeError('deep')
    try:
        inner()
    except RuntimeError as e:
        report = cr.format_report(e)
    assert 'inner' in report
    assert 'Traceback' in report


def test_clamp_report_trims_absurdly_long_lines():
    report = 'x' * 5000
    out = cr.clamp_report(report, max_line=100)
    assert len(out.splitlines()[0]) <= 110
    assert out.endswith('...')


def test_clamp_report_caps_total_size():
    report = '\n'.join('line %d' % i for i in range(10000))
    out = cr.clamp_report(report, max_report=500)
    assert len(out) <= 600
    assert 'truncated' in out


def test_clamp_report_leaves_normal_text_alone():
    report = 'Traceback (most recent call last):\n  File "x", line 1\nValueError: y'
    assert cr.clamp_report(report) == report


def test_write_and_read_round_trip():
    d = tempfile.mkdtemp()
    path = cr.write_crash(d, 'first failure')
    assert path and os.path.exists(path)
    assert 'first failure' in cr.read_crash(d)


def test_write_crash_appends_rather_than_replacing():
    d = tempfile.mkdtemp()
    cr.write_crash(d, 'first failure')
    cr.write_crash(d, 'second failure')
    body = cr.read_crash(d)
    assert 'first failure' in body
    assert 'second failure' in body


def test_write_crash_creates_a_missing_directory():
    d = os.path.join(tempfile.mkdtemp(), 'not', 'there', 'yet')
    path = cr.write_crash(d, 'made the dir')
    assert path and os.path.exists(path)


def test_write_crash_never_raises_when_it_cannot_write():
    # A handler must not crash while reporting a crash.
    assert cr.write_crash(None, 'nowhere') is None
    blocked = tempfile.mkdtemp()
    os.chmod(blocked, 0o500)
    try:
        cr.write_crash(os.path.join(blocked, 'sub'), 'denied')  # must not raise
    finally:
        os.chmod(blocked, 0o700)


def test_read_crash_with_no_log_is_empty():
    assert cr.read_crash(tempfile.mkdtemp()) == ''
    assert cr.read_crash(None) == ''


def test_clear_crash_removes_the_log():
    d = tempfile.mkdtemp()
    cr.write_crash(d, 'to be cleared')
    assert cr.clear_crash(d) is True
    assert cr.read_crash(d) == ''
    assert cr.clear_crash(d) is False      # already gone
