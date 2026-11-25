"""Make HTTPS verification work on Android.

Android ships no CA bundle that Python's ``ssl`` module can find, so every
HTTPS call fails on a packaged APK with::

    [SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer certificate

The previous approach was to set ``SSL_CERT_FILE`` and ``REQUESTS_CA_BUNDLE``
and hope OpenSSL picked them up. On the device it did not, and the failure was
silent: the only diagnostic was a ``logging.debug`` call that ran *before*
``logging.basicConfig``, so it went nowhere.

This module does three things instead, in order of how much we trust them:

1. finds a CA bundle (certifi first, then anything already configured, then
   the usual system locations) and reports what it found;
2. installs it as the default for ``urllib``/``http.client`` by replacing
   ``ssl._create_default_https_context`` - that covers Kivy's image loader and
   every ``urlopen`` in the app, whether or not the environment is honoured;
3. still exports the environment variables, because ``requests`` (used by
   tmdbv3api) reads ``REQUESTS_CA_BUNDLE`` and never touches our context.

Step 2 only happens when the interpreter's own default store is empty, which
is the precise condition that makes Android different from a desktop. On a
machine with a real CA store nothing is overridden, so a corporate root stays
in force.

No Kivy import here, so the whole module unit tests without a display.
"""

from __future__ import annotations

import logging
import os
import ssl

log = logging.getLogger(__name__)

#: Environment variables consulted by third-party HTTP libraries.
ENV_VARS = ('SSL_CERT_FILE', 'REQUESTS_CA_BUNDLE')

#: Where a CA bundle usually lives when there is no certifi.
SYSTEM_BUNDLES = (
    '/etc/ssl/certs/ca-certificates.crt',      # Debian, Ubuntu, Alpine
    '/etc/pki/tls/certs/ca-bundle.crt',        # Fedora, RHEL
    '/etc/ssl/cert.pem',                       # macOS, BSD
)

#: Kept so we can delegate to the real factory after installing a default.
_ORIGINAL_CREATE_DEFAULT_CONTEXT = ssl.create_default_context


def _usable(path):
    """A CA bundle is only usable if it exists and has something in it."""
    try:
        return bool(path) and os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:
        return False


def find_ca_bundle(env=None):
    """Locate a CA bundle, returning ``(path, source, problem)``.

    ``problem`` explains why certifi was not used, when it was not. It is
    shown to the user, so it must never contain anything secret - a file path
    and an exception message are all it ever holds.
    """
    environ = os.environ if env is None else env
    problem = None

    try:
        import certifi
    except Exception as exc:                     # pragma: no cover - env-specific
        problem = f'certifi did not import ({exc.__class__.__name__}: {exc})'
    else:
        try:
            path = certifi.where()
        except Exception as exc:                 # pragma: no cover - env-specific
            problem = f'certifi.where() failed ({exc.__class__.__name__}: {exc})'
        else:
            if _usable(path):
                return path, 'certifi', None
            problem = f'certifi points at {path}, which is missing or empty'

    for var in ENV_VARS:
        candidate = environ.get(var)
        if _usable(candidate):
            return candidate, var, problem

    for candidate in SYSTEM_BUNDLES:
        if _usable(candidate):
            return candidate, 'system', problem

    return None, None, problem or 'no CA bundle found in any known location'


def count_default_cas():
    """How many CA certificates the interpreter's default context loads.

    Zero is the signature of an Android build: ``ssl`` works, OpenSSL works,
    there is simply nothing to verify against.
    """
    try:
        ctx = _ORIGINAL_CREATE_DEFAULT_CONTEXT()
        return int(ctx.cert_store_stats().get('x509_ca', 0))
    except Exception:                            # pragma: no cover - env-specific
        return 0


class TlsSetup:
    """What ``configure`` did, in a form that can be shown to a user."""

    __slots__ = ('ca_path', 'source', 'problem', 'installed', 'ca_count')

    def __init__(self, ca_path, source, problem, installed, ca_count):
        self.ca_path = ca_path
        self.source = source
        self.problem = problem
        self.installed = installed
        self.ca_count = ca_count

    def __bool__(self):
        return self.ca_count > 0

    def __repr__(self):
        return (f'TlsSetup(source={self.source!r}, installed={self.installed}, '
                f'ca_count={self.ca_count})')

    def describe(self):
        """One short line for a log, a crash report or an error screen."""
        if self.ca_count and self.source:
            where = 'installed' if self.installed else 'already active'
            return (f'TLS: {self.ca_count} CAs from {self.source} ({where}). '
                    f'Bundle: {self.ca_path}')
        if self.ca_path:
            return (f'TLS: found a bundle at {self.ca_path} via {self.source}, '
                    f'but no certificates loaded from it.')
        return f'TLS: no CA bundle available - {self.problem}'


def configure(env=None, force=False):
    """Give the process a working CA store, and report what happened.

    Call once, early, after logging is configured. Safe to call again.
    """
    environ = os.environ if env is None else env
    ca_path, source, problem = find_ca_bundle(environ)

    before = count_default_cas()
    installed = False

    if ca_path and (force or before == 0):
        installed = _install_default_context(ca_path)

    if ca_path:
        # requests/urllib3 never see our context, so they still need these.
        for var in ENV_VARS:
            if not _usable(environ.get(var)):
                environ[var] = ca_path

    setup = TlsSetup(ca_path, source, problem, installed,
                     count_default_cas() if installed else before)

    if setup:
        log.info(setup.describe())
    else:
        log.warning(setup.describe())
    return setup


def _install_default_context(ca_path):
    """Point urllib and http.client at ``ca_path`` by default.

    Two steps, because one is not enough:

    * ``http.client._create_https_context`` calls
      ``ssl._create_default_https_context()``, so replacing that covers every
      HTTPS handler built from here on;
    * but ``urllib.request.urlopen`` builds one opener and caches it in a
      module global, and ``HTTPSHandler`` captures its context at construction
      time. An opener built before this ran would keep the empty store
      forever. Installing our own opener replaces it outright.

    Between them, every ``urlopen`` in the process is covered - Kivy's image
    loader included, which is how posters are fetched.
    """

    def _factory(purpose=ssl.Purpose.SERVER_AUTH, *, cafile=None,
                 capath=None, cadata=None):
        return _ORIGINAL_CREATE_DEFAULT_CONTEXT(
            purpose,
            cafile=cafile if cafile is not None else ca_path,
            capath=capath,
            cadata=cadata,
        )

    try:
        ssl._create_default_https_context = _factory
    except Exception:                            # pragma: no cover - env-specific
        log.exception('Could not install a default HTTPS context')
        return False

    try:
        import urllib.request

        urllib.request.install_opener(
            urllib.request.build_opener(
                urllib.request.HTTPSHandler(context=context(ca_path))
            )
        )
    except Exception:                            # pragma: no cover - env-specific
        log.exception('Could not install a default urllib opener')
        # The factory patch above is still in place, so report success only
        # for what actually happened.
        return False

    return True


def context(ca_path=None):
    """An explicit context for calls we make ourselves.

    Passing this to ``urlopen`` does not depend on the default having been
    replaced, so our own requests keep working even if that ever stops.

    This is called inline on every request, so it must never raise: a bundle
    that exists but is not valid PEM would otherwise turn every network call
    into an unexplained failure. Verification is never weakened - the fallback
    is the ordinary default context, which simply has nothing loaded.
    """
    path = ca_path or find_ca_bundle()[0]
    if _usable(path):
        try:
            return _ORIGINAL_CREATE_DEFAULT_CONTEXT(cafile=path)
        except Exception as exc:
            log.warning('CA bundle at %s could not be loaded: %s', path, exc)
    return _ORIGINAL_CREATE_DEFAULT_CONTEXT()


def looks_like_certificate_error(exc):
    """True when an exception is a CA-verification failure.

    Used to decide whether to show the user the TLS diagnostic alongside the
    error, rather than making them read it on every unrelated network blip.
    """
    if isinstance(exc, ssl.SSLCertVerificationError):
        return True
    text = str(exc)
    return 'CERTIFICATE_VERIFY_FAILED' in text or 'SSLCertVerificationError' in text
