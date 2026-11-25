"""Tests for the APK signature reader, and a guard on signing material.

The signature check exists so a build cannot silently change the key it signs
with: an APK signed by a different key will not install over the previous one,
and nothing else in CI would notice.
"""

import io
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))

import apk_signature as sig

ROOT = Path(__file__).resolve().parents[1]


def _plain_zip():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('AndroidManifest.xml', 'not really')
    return buffer.getvalue()


def _signed_apk(certificate=b'CERTIFICATE-BYTES'):
    """A zip carrying a minimal but correctly shaped v2 signing block."""
    def prefixed(payload):
        return struct.pack('<I', len(payload)) + payload

    certificates = prefixed(prefixed(certificate))
    digests = prefixed(b'')
    attributes = prefixed(b'')
    signed_data = prefixed(digests + certificates + attributes)
    signer = prefixed(signed_data)
    signers = prefixed(signer)

    pair_body = struct.pack('<I', 0x7109871a) + signers
    pair = struct.pack('<Q', len(pair_body)) + pair_body
    block_body = pair
    size = len(block_body) + 8 + len(MAGIC := sig.MAGIC)
    block = (struct.pack('<Q', size) + block_body
             + struct.pack('<Q', size) + MAGIC)

    base = _plain_zip()
    cd_offset = sig._find_central_directory(base)
    # Splice the block in between local entries and the central directory,
    # and fix the directory offset the end record points at.
    patched = base[:cd_offset] + block + base[cd_offset:]
    patched = patched.replace(
        struct.pack('<I', cd_offset), struct.pack('<I', cd_offset + len(block))
    )
    return patched


class TestParsing:
    def test_reads_the_certificate_from_a_v2_block(self):
        certificate, scheme = sig.signer_certificate(_signed_apk())
        assert certificate == b'CERTIFICATE-BYTES'
        assert scheme == 'v2'

    def test_rejects_a_file_that_is_not_a_zip(self):
        with pytest.raises(sig.SignatureError, match='not a zip'):
            sig.signer_certificate(b'this is not a zip file' * 10)

    def test_reports_an_unsigned_apk_clearly(self):
        with pytest.raises(sig.SignatureError, match='no APK Signing Block'):
            sig.signer_certificate(_plain_zip())


class TestFingerprint:
    def test_matches_the_format_keytool_prints(self):
        value = sig.fingerprint(b'')
        assert len(value) == 32 * 3 - 1
        assert value.count(':') == 31
        assert value.isupper()

    def test_is_stable_for_the_same_input(self):
        assert sig.fingerprint(b'abc') == sig.fingerprint(b'abc')

    def test_differs_for_different_certificates(self):
        assert sig.fingerprint(b'abc') != sig.fingerprint(b'abd')


class TestNormalise:
    def test_ignores_separators_and_case(self):
        assert sig.normalise('aa:bb:CC') == sig.normalise('AABBcc')

    def test_handles_none_and_blank(self):
        assert sig.normalise(None) == ''
        assert sig.normalise('  ') == ''


class TestCommandLine:
    def _run(self, path, *extra):
        return subprocess.run(
            [sys.executable, str(ROOT / 'tools' / 'apk_signature.py'),
             str(path), *extra],
            capture_output=True, text=True,
        )

    def test_prints_the_fingerprint(self, tmp_path):
        apk = tmp_path / 'app.apk'
        apk.write_bytes(_signed_apk())
        result = self._run(apk)
        assert result.returncode == 0
        assert sig.fingerprint(b'CERTIFICATE-BYTES') in result.stdout

    def test_accepts_the_expected_fingerprint(self, tmp_path):
        apk = tmp_path / 'app.apk'
        apk.write_bytes(_signed_apk())
        result = self._run(apk, '--expect', sig.fingerprint(b'CERTIFICATE-BYTES'))
        assert result.returncode == 0
        assert 'OK: signed with the expected key' in result.stdout

    def test_fails_on_a_different_key(self, tmp_path):
        apk = tmp_path / 'app.apk'
        apk.write_bytes(_signed_apk())
        result = self._run(apk, '--expect', 'AA:BB:CC')
        assert result.returncode == 1
        assert 'not signed with the expected key' in result.stderr

    def test_fails_cleanly_on_an_unsigned_apk(self, tmp_path):
        apk = tmp_path / 'app.apk'
        apk.write_bytes(_plain_zip())
        result = self._run(apk)
        assert result.returncode == 2
        assert 'no APK Signing Block' in result.stderr


class TestNoSigningMaterialInRepo:
    """The keystore lives in a repository secret, never in the tree.

    This repo shipped a working API key for most of its history. The same
    mistake with a signing key would be worse, so it gets the same guard.
    """

    SUFFIXES = ('.keystore', '.jks', '.p12', '.pfx')

    def test_no_keystore_file_is_tracked(self):
        tracked = subprocess.run(
            ['git', 'ls-files'], cwd=ROOT, capture_output=True, text=True,
        ).stdout.split()
        offenders = [
            name for name in tracked
            if name.lower().endswith(self.SUFFIXES)
        ]
        assert not offenders, f'signing material committed: {offenders}'

    def test_gitignore_covers_keystores(self):
        patterns = (ROOT / '.gitignore').read_text()
        for suffix in ('*.keystore', '*.jks', '*.p12'):
            assert suffix in patterns, f'{suffix} is not gitignored'
