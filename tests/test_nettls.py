"""Tests for CA-bundle discovery and the default HTTPS context.

These cover the Android failure directly: an interpreter whose default
certificate store is empty must end up with a working one, and when it cannot,
it must say so in a line a user can read off a phone screen.
"""

import http.server
import os
import shutil
import ssl
import subprocess
import tempfile
import threading
import urllib.request

import pytest

import nettls


def _self_signed(path):
    """A real single-certificate PEM, so load_verify_locations accepts it."""
    subprocess.run(
        ['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-keyout', path,
         '-out', path, '-days', '1', '-nodes', '-subj', '/CN=localhost',
         '-addext', 'subjectAltName=DNS:localhost'],
        check=True, capture_output=True,
    )
    return path


@pytest.fixture(scope='session')
def bundle(tmp_path_factory):
    """A genuine CA bundle. Generated once; these tests never mutate it."""
    if shutil.which('openssl') is None:
        pytest.skip('needs openssl')
    return _self_signed(str(tmp_path_factory.mktemp('ca') / 'bundle.pem'))


@pytest.fixture
def junk_bundle(tmp_path):
    """A non-empty file that is not a certificate - a packaging mishap."""
    path = tmp_path / 'notacert.pem'
    path.write_text('-- this is not a certificate --\n')
    return str(path)


@pytest.fixture
def restore_default_context():
    original = ssl._create_default_https_context
    opener = urllib.request._opener
    yield
    ssl._create_default_https_context = original
    urllib.request._opener = opener


class TestUsable:
    def test_rejects_missing_file(self):
        assert nettls._usable('/no/such/bundle.pem') is False

    def test_rejects_empty_file(self):
        handle, path = tempfile.mkstemp()
        os.close(handle)
        assert nettls._usable(path) is False

    def test_rejects_none_and_empty_string(self):
        assert nettls._usable(None) is False
        assert nettls._usable('') is False

    def test_accepts_a_non_empty_file(self, bundle):
        assert nettls._usable(bundle) is True

    def test_rejects_a_directory(self):
        assert nettls._usable(tempfile.mkdtemp()) is False


class TestFindCaBundle:
    def test_prefers_certifi_when_it_is_installed(self):
        certifi = pytest.importorskip('certifi')
        path, source, problem = nettls.find_ca_bundle(env={})
        assert source == 'certifi'
        assert path == certifi.where()
        assert problem is None

    def test_falls_back_to_the_environment(self, bundle, monkeypatch):
        monkeypatch.setattr(nettls, 'SYSTEM_BUNDLES', ())
        monkeypatch.setitem(
            __import__('sys').modules, 'certifi', None
        )  # import certifi -> ImportError
        path, source, problem = nettls.find_ca_bundle(
            env={'SSL_CERT_FILE': bundle}
        )
        assert path == bundle
        assert source == 'SSL_CERT_FILE'
        assert problem is not None

    def test_ignores_an_environment_path_that_does_not_exist(self, monkeypatch):
        monkeypatch.setattr(nettls, 'SYSTEM_BUNDLES', ())
        monkeypatch.setitem(__import__('sys').modules, 'certifi', None)
        path, source, problem = nettls.find_ca_bundle(
            env={'SSL_CERT_FILE': '/gone/missing.pem'}
        )
        assert path is None
        assert source is None
        assert problem

    def test_reports_a_problem_when_nothing_is_available(self, monkeypatch):
        monkeypatch.setattr(nettls, 'SYSTEM_BUNDLES', ())
        monkeypatch.setitem(__import__('sys').modules, 'certifi', None)
        path, source, problem = nettls.find_ca_bundle(env={})
        assert path is None
        assert 'certifi' in problem


class TestConfigure:
    def test_installs_a_default_when_the_store_is_empty(
        self, bundle, monkeypatch, restore_default_context
    ):
        """The Android case: ssl works, but nothing is loaded to verify against."""
        monkeypatch.setattr(nettls, 'count_default_cas', lambda: 0)
        monkeypatch.setattr(
            nettls, 'find_ca_bundle', lambda env=None: (bundle, 'certifi', None)
        )
        setup = nettls.configure(env={})
        assert setup.installed is True
        assert ssl._create_default_https_context is not ssl.create_default_context

    def test_leaves_a_working_store_alone(self, bundle, monkeypatch):
        """A desktop with a real CA store keeps it, corporate roots included."""
        monkeypatch.setattr(nettls, 'count_default_cas', lambda: 150)
        monkeypatch.setattr(
            nettls, 'find_ca_bundle', lambda env=None: (bundle, 'system', None)
        )
        before = ssl._create_default_https_context
        setup = nettls.configure(env={})
        assert setup.installed is False
        assert ssl._create_default_https_context is before

    def test_exports_the_environment_variables_for_requests(
        self, bundle, monkeypatch
    ):
        """tmdbv3api uses requests, which never sees our context."""
        monkeypatch.setattr(nettls, 'count_default_cas', lambda: 150)
        monkeypatch.setattr(
            nettls, 'find_ca_bundle', lambda env=None: (bundle, 'certifi', None)
        )
        env = {}
        nettls.configure(env=env)
        assert env['SSL_CERT_FILE'] == bundle
        assert env['REQUESTS_CA_BUNDLE'] == bundle

    def test_does_not_clobber_a_usable_environment_value(self, bundle, monkeypatch):
        other = tempfile.mkstemp(suffix='.pem')[1]
        with open(other, 'w') as fh:
            fh.write('existing\n')
        monkeypatch.setattr(nettls, 'count_default_cas', lambda: 150)
        monkeypatch.setattr(
            nettls, 'find_ca_bundle', lambda env=None: (bundle, 'certifi', None)
        )
        env = {'SSL_CERT_FILE': other}
        nettls.configure(env=env)
        assert env['SSL_CERT_FILE'] == other

    def test_replaces_an_environment_value_pointing_nowhere(self, bundle, monkeypatch):
        monkeypatch.setattr(nettls, 'count_default_cas', lambda: 150)
        monkeypatch.setattr(
            nettls, 'find_ca_bundle', lambda env=None: (bundle, 'certifi', None)
        )
        env = {'SSL_CERT_FILE': '/gone/missing.pem'}
        nettls.configure(env=env)
        assert env['SSL_CERT_FILE'] == bundle

    def test_force_installs_even_when_a_store_already_exists(
        self, bundle, monkeypatch, restore_default_context
    ):
        """What main.py does on Android, where a store may exist but not work."""
        monkeypatch.setattr(nettls, 'count_default_cas', lambda: 150)
        monkeypatch.setattr(
            nettls, 'find_ca_bundle', lambda env=None: (bundle, 'certifi', None)
        )
        assert nettls.configure(env={}, force=True).installed is True

    def test_force_is_harmless_when_there_is_no_bundle(
        self, monkeypatch, restore_default_context
    ):
        monkeypatch.setattr(nettls, 'count_default_cas', lambda: 150)
        monkeypatch.setattr(
            nettls, 'find_ca_bundle', lambda env=None: (None, None, 'nothing')
        )
        assert nettls.configure(env={}, force=True).installed is False

    def test_survives_having_no_bundle_at_all(self, monkeypatch):
        monkeypatch.setattr(nettls, 'count_default_cas', lambda: 0)
        monkeypatch.setattr(
            nettls, 'find_ca_bundle', lambda env=None: (None, None, 'nothing found')
        )
        setup = nettls.configure(env={})
        assert bool(setup) is False
        assert setup.installed is False
        assert 'nothing found' in setup.describe()


class TestDescribe:
    def test_names_the_source_and_count_on_success(self, bundle):
        setup = nettls.TlsSetup(bundle, 'certifi', None, True, 147)
        text = setup.describe()
        assert '147' in text and 'certifi' in text and bundle in text

    def test_explains_the_failure_when_nothing_was_found(self):
        setup = nettls.TlsSetup(None, None, 'certifi did not import', False, 0)
        assert 'no CA bundle' in setup.describe()
        assert 'certifi did not import' in setup.describe()

    def test_flags_a_bundle_that_loaded_nothing(self, bundle):
        setup = nettls.TlsSetup(bundle, 'certifi', None, True, 0)
        assert 'no certificates loaded' in setup.describe()

    def test_repr_is_short_and_has_no_path(self, bundle):
        assert bundle not in repr(nettls.TlsSetup(bundle, 'certifi', None, True, 9))


class TestContext:
    def test_returns_a_context_even_with_no_bundle(self, monkeypatch):
        monkeypatch.setattr(
            nettls, 'find_ca_bundle', lambda env=None: (None, None, 'none')
        )
        assert isinstance(nettls.context(), ssl.SSLContext)

    def test_verification_stays_on(self):
        ctx = nettls.context()
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx.check_hostname is True

    def test_loads_the_bundle_it_is_given(self):
        certifi = pytest.importorskip('certifi')
        ctx = nettls.context(certifi.where())
        assert ctx.cert_store_stats()['x509_ca'] > 0

    def test_a_corrupt_bundle_does_not_raise(self, junk_bundle):
        """Called inline on every request, so raising would break them all."""
        ctx = nettls.context(junk_bundle)
        assert isinstance(ctx, ssl.SSLContext)
        assert ctx.verify_mode == ssl.CERT_REQUIRED

    def test_a_corrupt_bundle_is_reported_rather_than_installed(
        self, junk_bundle, monkeypatch, restore_default_context
    ):
        monkeypatch.setattr(nettls, 'count_default_cas', lambda: 0)
        monkeypatch.setattr(
            nettls, 'find_ca_bundle',
            lambda env=None: (junk_bundle, 'certifi', None),
        )
        setup = nettls.configure(env={})
        assert bool(setup) is False
        assert 'no certificates loaded' in setup.describe()


@pytest.mark.skipif(shutil.which('openssl') is None, reason='needs openssl')
class TestAgainstARealServer:
    """End-to-end against a live HTTPS server, reproducing the Android case.

    An empty default CA store is the whole of what makes Android different.
    These tests create that condition, confirm a plain urlopen fails exactly
    as it did on the phone, and confirm configure() repairs it.
    """

    @staticmethod
    def _serve(tmp_path):
        cert = str(tmp_path / 'server.pem')
        subprocess.run(
            ['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-keyout', cert,
             '-out', cert, '-days', '1', '-nodes', '-subj', '/CN=localhost',
             '-addext', 'subjectAltName=DNS:localhost'],
            check=True, capture_output=True,
        )
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert)
        httpd = http.server.HTTPServer(
            ('127.0.0.1', 0), http.server.SimpleHTTPRequestHandler
        )
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        return cert, f'https://localhost:{httpd.server_address[1]}/', httpd

    def test_plain_urlopen_works_once_configured(
        self, tmp_path, monkeypatch, restore_default_context
    ):
        cert, url, httpd = self._serve(tmp_path)
        try:
            monkeypatch.setattr(nettls, 'count_default_cas', lambda: 0)
            monkeypatch.setattr(
                nettls, 'find_ca_bundle', lambda env=None: (cert, 'certifi', None)
            )

            # Build and cache an opener first. urlopen stores one in a module
            # global and HTTPSHandler captures its context at construction, so
            # patching the ssl factory alone leaves this one broken forever.
            with pytest.raises(Exception) as caught:
                urllib.request.urlopen(url, timeout=5)
            assert nettls.looks_like_certificate_error(caught.value)

            assert nettls.configure(env={}).installed is True

            # No context argument: this is the call Kivy's image loader makes.
            with urllib.request.urlopen(url, timeout=5) as resp:
                assert resp.status == 200
        finally:
            httpd.shutdown()

    def test_explicit_context_works_independently_of_the_default(
        self, tmp_path, restore_default_context
    ):
        cert, url, httpd = self._serve(tmp_path)
        try:
            with urllib.request.urlopen(
                url, timeout=5, context=nettls.context(cert)
            ) as resp:
                assert resp.status == 200
        finally:
            httpd.shutdown()


class TestLooksLikeCertificateError:
    def test_recognises_the_real_exception(self):
        exc = ssl.SSLCertVerificationError('certificate verify failed')
        assert nettls.looks_like_certificate_error(exc) is True

    def test_recognises_the_message_android_produces(self):
        exc = OSError(
            '<urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify '
            'failed: unable to get local issuer certificate (_ssl.c:1081)>'
        )
        assert nettls.looks_like_certificate_error(exc) is True

    def test_ignores_an_ordinary_network_error(self):
        assert nettls.looks_like_certificate_error(
            OSError('[Errno 101] Network is unreachable')
        ) is False

    def test_ignores_a_timeout(self):
        assert nettls.looks_like_certificate_error(TimeoutError('timed out')) is False
