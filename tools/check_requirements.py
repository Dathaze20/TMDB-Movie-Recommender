#!/usr/bin/env python3
"""Check that every third-party import is declared in buildozer.spec.

A package missing from buildozer.spec does not fail the build. It fails on the
phone, as an ImportError at startup - the app opens, goes dark and closes,
with the reason only in logcat. This turns that into a CI failure with a name
attached.

Run from the repository root:  python3 tools/check_requirements.py
"""

from __future__ import annotations

import ast
import configparser
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Import name -> the distribution name as it must appear in buildozer.spec.
# Only needed where the two differ.
IMPORT_TO_DIST = {
    'dotenv': 'python_dotenv',
    'PIL': 'pillow',
    'jnius': 'pyjnius',
    'android': 'android',
    'yaml': 'pyyaml',
}

# Provided by python-for-android itself via the bootstrap, so they need no
# entry in requirements even though they are not in the standard library.
PROVIDED_BY_P4A = {'android', 'jnius'}

SKIP_DIRS = {'.git', '.buildozer', 'bin', 'tests', '__pycache__', '.pytest_cache'}


def app_modules():
    """Modules that live in this repository, so are not dependencies."""
    names = set()
    for entry in os.listdir(ROOT):
        if entry.endswith('.py'):
            names.add(entry[:-3])
        elif os.path.isdir(os.path.join(ROOT, entry)) and \
                os.path.exists(os.path.join(ROOT, entry, '__init__.py')):
            names.add(entry)
    return names


def source_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith('.py') and not fn.startswith('check_requirements'):
                yield os.path.join(dirpath, fn)


def imports_in(path):
    """Every top-level module name imported by a file, nested ones included."""
    with open(path, 'r', encoding='utf-8') as fh:
        tree = ast.parse(fh.read(), filename=path)
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:          # relative import: local to the repo
                continue
            if node.module:
                found.add(node.module.split('.')[0])
    return found


def declared_requirements():
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join(ROOT, 'buildozer.spec'))
    raw = cfg['app']['requirements']
    names = set()
    for part in raw.split(','):
        part = part.strip()
        if not part:
            continue
        name = re.split(r'[=<>!~\[]', part, maxsplit=1)[0].strip().lower()
        names.add(name)
        # buildozer.spec and PyPI disagree about - vs _; accept either.
        names.add(name.replace('-', '_'))
        names.add(name.replace('_', '-'))
    return names


def main():
    stdlib = set(sys.stdlib_module_names)
    local = app_modules()
    declared = declared_requirements()

    missing = {}
    for path in sorted(source_files()):
        rel = os.path.relpath(path, ROOT)
        for mod in sorted(imports_in(path)):
            if mod in stdlib or mod in local or mod in PROVIDED_BY_P4A:
                continue
            dist = IMPORT_TO_DIST.get(mod, mod).lower()
            if dist in declared or dist.replace('-', '_') in declared:
                continue
            missing.setdefault(dist, set()).add(f"{rel} (import {mod})")

    print('buildozer.spec requirements:', ', '.join(sorted(
        d for d in declared if '-' not in d)))
    print()
    if missing:
        print('::error::Imports missing from buildozer.spec requirements:')
        for dist, where in sorted(missing.items()):
            print(f"  {dist}")
            for w in sorted(where):
                print(f"      used by {w}")
        print()
        print('Add each to the requirements line in buildozer.spec. Without it '
              'the APK builds fine and then fails on the phone with an '
              'ImportError at startup.')
        return 1

    print('OK: every third-party import is declared.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
