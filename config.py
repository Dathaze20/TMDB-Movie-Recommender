"""TMDB API-key resolution and storage.

Resolution order (first hit wins):

1. the ``TMDB_API_KEY`` environment variable - the development path;
2. a ``.env`` file beside the project, when ``python-dotenv`` is installed;
3. a key the user typed into the app, saved under the app's data directory.

There is deliberately **no** bundled fallback key. The repository shipped one
for most of its history, in a public repo, which meant the key was exposed to
anyone who read the source. When none of the above yields a key the app shows
its setup screen and makes zero API requests.

No Kivy import here, so the whole module unit tests without a display.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
import tempfile

log = logging.getLogger(__name__)

ENV_VAR = 'TMDB_API_KEY'
CREDENTIALS_FILENAME = 'credentials.json'

#: Where TMDB hands out keys, shown on the setup screen.
TMDB_SIGNUP_URL = 'https://www.themoviedb.org/settings/api'

#: Sources reported by resolve_api_key, in precedence order.
SOURCE_ENV = 'environment'
SOURCE_DOTENV = 'dotenv'
SOURCE_SAVED = 'saved'


def load_dotenv_file(path='.env'):
    """Load ``path`` into os.environ if python-dotenv is available.

    Returns True only when a file was actually read. Existing environment
    variables always win, so an exported TMDB_API_KEY overrides .env.
    """
    if not os.path.isfile(path):
        return False
    try:
        from dotenv import load_dotenv as _load
    except ImportError:
        log.info("Found %s but python-dotenv is not installed; ignoring it.", path)
        return False
    try:
        return bool(_load(path, override=False))
    except OSError as exc:
        log.warning("Could not read %s: %s", path, exc)
        return False


def default_data_dir(app_dirname='tmdb-movie-recommender'):
    """A platform-appropriate per-user data directory.

    The Kivy app passes App.user_data_dir instead; this exists so the non-UI
    code (and the tests) has a sane answer without importing Kivy.
    """
    if sys.platform == 'win32':
        base = os.environ.get('APPDATA') or os.path.expanduser('~')
    elif sys.platform == 'darwin':
        base = os.path.join(os.path.expanduser('~'), 'Library', 'Application Support')
    else:
        base = os.environ.get('XDG_DATA_HOME') or os.path.join(
            os.path.expanduser('~'), '.local', 'share'
        )
    return os.path.join(base, app_dirname)


def _suppress_os_error(func, *args):
    """Best-effort cleanup: run func and swallow OS errors."""
    with contextlib.suppress(OSError):
        func(*args)


def atomic_write(path, payload, mode=0o600):
    """Write payload to path without risking a half-written file.

    The content lands in a temp file in the same directory and is then moved
    into place with os.replace, which is atomic on POSIX and Windows.
    """
    directory = os.path.dirname(os.path.abspath(path)) or '.'
    os.makedirs(directory, exist_ok=True)
    handle, tmp_path = tempfile.mkstemp(dir=directory, prefix='.tmp-', suffix='.json')
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        # Filesystems such as FAT (common on Android SD cards) ignore
        # permission bits. Not fatal - carry on without them.
        with contextlib.suppress(OSError):
            os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)
    except BaseException:
        _suppress_os_error(os.unlink, tmp_path)
        raise


class ApiKeyStore:
    """Reads and writes the user-supplied key in its own restricted file.

    The credential lives apart from favorites.json so that file can be copied
    or shared without leaking the key.
    """

    def __init__(self, data_dir, filename=CREDENTIALS_FILENAME):
        self.data_dir = data_dir
        self.path = os.path.join(data_dir, filename)

    def read(self):
        try:
            with open(self.path, encoding='utf-8') as fh:
                payload = json.load(fh)
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            log.warning("Could not read stored credentials: %s", exc)
            return None
        if not isinstance(payload, dict):
            return None
        key = payload.get('api_key')
        return key.strip() if isinstance(key, str) and key.strip() else None

    def write(self, api_key):
        cleaned = (api_key or '').strip()
        if not cleaned:
            raise ValueError('Refusing to store an empty API key')
        atomic_write(self.path, json.dumps({'api_key': cleaned}, indent=2))

    def clear(self):
        _suppress_os_error(os.unlink, self.path)


class ResolvedKey:
    """The outcome of resolve_api_key: the key, and where it came from."""

    __slots__ = ('key', 'source')

    def __init__(self, key, source):
        self.key = key
        self.source = source

    def __bool__(self):
        return bool(self.key)

    def __repr__(self):
        # Deliberately never renders the key itself.
        return f'ResolvedKey(source={self.source!r}, present={bool(self.key)})'

    @property
    def is_editable(self):
        """Environment-provided keys are owned by the shell, not the app."""
        return self.source in (None, SOURCE_SAVED)


def resolve_api_key(data_dir=None, env=None, dotenv_path='.env', use_dotenv=True):
    """Find a usable TMDB key, reporting where it came from.

    ``env`` lets the caller pass a snapshot of the environment rather than
    reading os.environ live. That matters because tmdbv3api's ``api_key``
    setter writes straight into ``os.environ['TMDB_API_KEY']``, so by the time
    the app asks a second time the real environment may have been overwritten.
    """
    environ = os.environ if env is None else env

    direct = (environ.get(ENV_VAR) or '').strip()
    if direct:
        return ResolvedKey(direct, SOURCE_ENV)

    # dotenv writes into os.environ, so read the result back from there even
    # when the caller supplied a snapshot for the step above.
    if use_dotenv and load_dotenv_file(dotenv_path):
        from_dotenv = (os.environ.get(ENV_VAR) or '').strip()
        if from_dotenv:
            return ResolvedKey(from_dotenv, SOURCE_DOTENV)

    directory = data_dir or default_data_dir()
    saved = ApiKeyStore(directory).read()
    if saved:
        return ResolvedKey(saved, SOURCE_SAVED)

    return ResolvedKey(None, None)


def looks_like_api_key(candidate):
    """Cheap client-side check before spending a network round-trip.

    TMDB v3 keys are 32-character hex strings. This only rejects obvious
    typos; the authoritative check is a live request.
    """
    cleaned = (candidate or '').strip()
    return len(cleaned) == 32 and all(c in '0123456789abcdef' for c in cleaned.lower())
