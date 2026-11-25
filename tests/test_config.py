"""Tests for API-key resolution, storage and the no-bundled-key guarantee."""

import json
import os
import re
import tempfile
from pathlib import Path

import pytest

import config
from config import (
    ENV_VAR,
    SOURCE_ENV,
    SOURCE_SAVED,
    ApiKeyStore,
    looks_like_api_key,
    resolve_api_key,
)

VALID_KEY = 'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6'


@pytest.fixture
def data_dir():
    return tempfile.mkdtemp()


class TestNoBundledKey:
    """The repository must never ship a working credential again.

    It shipped one for most of its history, in a public repo. These tests are
    the guard against that coming back.
    """

    def test_resolution_returns_nothing_when_unconfigured(self, data_dir):
        resolved = resolve_api_key(data_dir=data_dir, env={}, use_dotenv=False)
        assert resolved.key is None
        assert resolved.source is None
        assert bool(resolved) is False

    def test_config_module_defines_no_default_key(self):
        for name, value in vars(config).items():
            if isinstance(value, str) and looks_like_api_key(value):
                raise AssertionError(f'config.{name} looks like a bundled API key')

    def test_source_files_contain_no_32_char_hex_literals(self):
        root = Path(__file__).resolve().parents[1]
        pattern = re.compile(r"""['"][0-9a-f]{32}['"]""")
        offenders = []
        for path in list(root.glob('*.py')) + list(root.glob('*.spec')):
            if path.name.startswith('test_'):
                continue
            for num, line in enumerate(
                path.read_text(encoding='utf-8').splitlines(), 1
            ):
                if pattern.search(line):
                    offenders.append(f'{path.name}:{num}')
        assert not offenders, (
            'Possible hardcoded API key at: ' + ', '.join(offenders)
        )

    def test_resolved_key_repr_does_not_leak_the_key(self):
        resolved = resolve_api_key(env={ENV_VAR: VALID_KEY}, use_dotenv=False)
        assert VALID_KEY not in repr(resolved)


class TestLooksLikeApiKey:
    def test_accepts_a_real_shaped_key(self):
        assert looks_like_api_key(VALID_KEY) is True

    def test_accepts_uppercase_hex(self):
        assert looks_like_api_key(VALID_KEY.upper()) is True

    def test_tolerates_surrounding_whitespace(self):
        assert looks_like_api_key(f'  {VALID_KEY}\n') is True

    def test_rejects_wrong_length(self):
        assert looks_like_api_key('abc') is False
        assert looks_like_api_key('a' * 31) is False
        assert looks_like_api_key('a' * 33) is False

    def test_rejects_non_hex_characters(self):
        assert looks_like_api_key('z' * 32) is False

    def test_rejects_empty_and_none(self):
        assert looks_like_api_key('') is False
        assert looks_like_api_key(None) is False


class TestResolutionOrder:
    def test_environment_wins_over_saved(self, data_dir):
        ApiKeyStore(data_dir).write('s' * 32)
        resolved = resolve_api_key(
            data_dir=data_dir, env={ENV_VAR: VALID_KEY}, use_dotenv=False
        )
        assert resolved.key == VALID_KEY
        assert resolved.source == SOURCE_ENV

    def test_saved_key_is_used_when_environment_is_empty(self, data_dir):
        ApiKeyStore(data_dir).write(VALID_KEY)
        resolved = resolve_api_key(data_dir=data_dir, env={}, use_dotenv=False)
        assert resolved.key == VALID_KEY
        assert resolved.source == SOURCE_SAVED

    def test_blank_environment_value_falls_through_to_saved(self, data_dir):
        ApiKeyStore(data_dir).write(VALID_KEY)
        resolved = resolve_api_key(
            data_dir=data_dir, env={ENV_VAR: '   '}, use_dotenv=False
        )
        assert resolved.source == SOURCE_SAVED

    def test_environment_value_is_stripped(self, data_dir):
        resolved = resolve_api_key(
            data_dir=data_dir, env={ENV_VAR: f'  {VALID_KEY}\n'}, use_dotenv=False
        )
        assert resolved.key == VALID_KEY


class TestIsEditable:
    def test_environment_keys_are_not_editable_in_app(self, data_dir):
        resolved = resolve_api_key(
            data_dir=data_dir, env={ENV_VAR: VALID_KEY}, use_dotenv=False
        )
        assert resolved.is_editable is False

    def test_saved_keys_are_editable(self, data_dir):
        ApiKeyStore(data_dir).write(VALID_KEY)
        resolved = resolve_api_key(data_dir=data_dir, env={}, use_dotenv=False)
        assert resolved.is_editable is True

    def test_absent_key_is_editable(self, data_dir):
        resolved = resolve_api_key(data_dir=data_dir, env={}, use_dotenv=False)
        assert resolved.is_editable is True


class TestEnvironmentSnapshot:
    """tmdbv3api's api_key setter writes into os.environ['TMDB_API_KEY'].

    Assigning it - '' especially - therefore erases a key the user exported.
    main.py snapshots the environment at import and resolves against that, so
    resolution must honour the snapshot even once os.environ has been clobbered.
    """

    def test_snapshot_is_used_even_after_os_environ_is_overwritten(
        self, data_dir, monkeypatch
    ):
        snapshot = {ENV_VAR: VALID_KEY}
        monkeypatch.setenv(ENV_VAR, '')          # what tmdbv3api would do
        resolved = resolve_api_key(
            data_dir=data_dir, env=snapshot, use_dotenv=False
        )
        assert resolved.key == VALID_KEY
        assert resolved.source == SOURCE_ENV

    def test_snapshot_without_a_key_still_falls_through_to_saved(self, data_dir):
        ApiKeyStore(data_dir).write(VALID_KEY)
        resolved = resolve_api_key(data_dir=data_dir, env={}, use_dotenv=False)
        assert resolved.source == SOURCE_SAVED


class TestApiKeyStore:
    def test_write_then_read_round_trip(self, data_dir):
        store = ApiKeyStore(data_dir)
        store.write(VALID_KEY)
        assert store.read() == VALID_KEY

    def test_read_with_no_file_is_none(self, data_dir):
        assert ApiKeyStore(data_dir).read() is None

    def test_write_strips_whitespace(self, data_dir):
        store = ApiKeyStore(data_dir)
        store.write(f'  {VALID_KEY}  ')
        assert store.read() == VALID_KEY

    def test_write_refuses_an_empty_key(self, data_dir):
        with pytest.raises(ValueError):
            ApiKeyStore(data_dir).write('   ')

    def test_clear_removes_the_key(self, data_dir):
        store = ApiKeyStore(data_dir)
        store.write(VALID_KEY)
        store.clear()
        assert store.read() is None

    def test_clear_is_safe_when_nothing_is_stored(self, data_dir):
        ApiKeyStore(data_dir).clear()      # must not raise

    def test_corrupt_file_reads_as_none_rather_than_raising(self, data_dir):
        store = ApiKeyStore(data_dir)
        os.makedirs(data_dir, exist_ok=True)
        with open(store.path, 'w', encoding='utf-8') as fh:
            fh.write('{not json')
        assert store.read() is None

    def test_unexpected_json_shape_reads_as_none(self, data_dir):
        store = ApiKeyStore(data_dir)
        os.makedirs(data_dir, exist_ok=True)
        with open(store.path, 'w', encoding='utf-8') as fh:
            json.dump(['not', 'a', 'dict'], fh)
        assert store.read() is None

    def test_credentials_live_apart_from_the_watchlist(self, data_dir):
        store = ApiKeyStore(data_dir)
        store.write(VALID_KEY)
        assert os.path.basename(store.path) == config.CREDENTIALS_FILENAME
        assert 'favorites' not in store.path

    def test_write_creates_a_missing_directory(self):
        nested = os.path.join(tempfile.mkdtemp(), 'not', 'there')
        store = ApiKeyStore(nested)
        store.write(VALID_KEY)
        assert store.read() == VALID_KEY


class TestAtomicWrite:
    def test_leaves_no_temp_files_behind(self, data_dir):
        path = os.path.join(data_dir, 'thing.json')
        config.atomic_write(path, '{"a": 1}')
        leftovers = [n for n in os.listdir(data_dir) if n.startswith('.tmp-')]
        assert leftovers == []

    def test_replaces_existing_content_entirely(self, data_dir):
        path = os.path.join(data_dir, 'thing.json')
        config.atomic_write(path, 'a long original payload')
        config.atomic_write(path, 'short')
        with open(path, encoding='utf-8') as fh:
            assert fh.read() == 'short'


class TestDefaultDataDir:
    def test_returns_an_absolute_path_naming_the_app(self):
        path = config.default_data_dir()
        assert os.path.isabs(path)
        assert 'tmdb-movie-recommender' in path
