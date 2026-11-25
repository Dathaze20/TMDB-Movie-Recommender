#!/usr/bin/env python3
"""Print, and optionally check, the certificate an APK was signed with.

Android refuses to install an APK over one signed by a different key, so a
build that quietly changes its signing key produces a package that can only be
installed by uninstalling the app first - losing the user's watchlist. That is
exactly what happened for the first few releases: every CI runner generated a
fresh throwaway debug keystore.

The workflow now restores a fixed keystore and calls this afterwards to prove
the APK really was signed with it. Comparing fingerprints catches a silent
fallback that a green build would otherwise hide.

Usage::

    python tools/apk_signature.py app.apk
    python tools/apk_signature.py app.apk --expect AA:BB:...

APKs targeting minSdk 24+ are commonly signed with APK Signature Scheme v2/v3
only, with no META-INF/*.RSA to read, so the signing block has to be parsed
out of the archive directly. Uses only the standard library, so it runs in CI
without installing the Android build tools.
"""

from __future__ import annotations

import argparse
import hashlib
import struct
import sys

MAGIC = b'APK Sig Block 42'
EOCD_SIGNATURE = b'PK\x05\x06'
EOCD_MIN_SIZE = 22
MAX_COMMENT = 65535

#: Block IDs that carry a signer list we can read.
SCHEMES = {
    0x7109871a: 'v2',
    0xf05368c0: 'v3',
}


class SignatureError(Exception):
    """The APK could not be parsed, or carries no signature we understand."""


def _find_central_directory(data):
    """Offset of the central directory, found via the end-of-archive record."""
    earliest = max(0, len(data) - EOCD_MIN_SIZE - MAX_COMMENT)
    for i in range(len(data) - EOCD_MIN_SIZE, earliest - 1, -1):
        if data[i:i + 4] == EOCD_SIGNATURE:
            return struct.unpack_from('<I', data, i + 16)[0]
    raise SignatureError('not a zip archive: no end-of-central-directory record')


def _length_prefixed(buf):
    """Iterate a sequence of uint32-length-prefixed items."""
    offset = 0
    while offset + 4 <= len(buf):
        size = struct.unpack_from('<I', buf, offset)[0]
        offset += 4
        if offset + size > len(buf):
            raise SignatureError('truncated length-prefixed sequence')
        yield buf[offset:offset + size]
        offset += size


def signing_block(data):
    """Return the APK Signing Block's payload, without its header or footer."""
    cd_offset = _find_central_directory(data)
    if cd_offset < 24 or data[cd_offset - 16:cd_offset] != MAGIC:
        raise SignatureError(
            'no APK Signing Block - the APK is unsigned, or uses v1 JAR '
            'signing only'
        )
    size = struct.unpack_from('<Q', data, cd_offset - 24)[0]
    start = cd_offset - 8 - size
    if start < 0:
        raise SignatureError('APK Signing Block size is out of range')
    return data[start + 8:cd_offset - 24]


def signer_certificate(data):
    """The DER bytes of the first signer certificate, and the scheme used."""
    block = signing_block(data)
    offset = 0
    while offset + 12 <= len(block):
        pair_size = struct.unpack_from('<Q', block, offset)[0]
        pair_id = struct.unpack_from('<I', block, offset + 8)[0]
        value = block[offset + 12:offset + 8 + pair_size]
        offset += 8 + pair_size
        if pair_id not in SCHEMES:
            continue
        signers_size = struct.unpack_from('<I', value, 0)[0]
        for signer in _length_prefixed(value[4:4 + signers_size]):
            signed_data = next(_length_prefixed(signer), None)
            if signed_data is None:
                continue
            sections = list(_length_prefixed(signed_data))
            if len(sections) < 2:
                continue
            # signed data is: digests, certificates, additional attributes
            for certificate in _length_prefixed(sections[1]):
                return certificate, SCHEMES[pair_id]
    raise SignatureError('no v2/v3 signer certificate found in the APK')


def fingerprint(certificate_der):
    """SHA-256 of the certificate, formatted the way keytool prints it."""
    digest = hashlib.sha256(certificate_der).hexdigest().upper()
    return ':'.join(digest[i:i + 2] for i in range(0, len(digest), 2))


def normalise(value):
    """Compare fingerprints without caring about separators or case."""
    return (value or '').replace(':', '').replace(' ', '').strip().upper()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('apk', help='path to the .apk file')
    parser.add_argument(
        '--expect',
        help='SHA-256 fingerprint the APK must be signed with; '
             'exits non-zero if it is not',
    )
    args = parser.parse_args(argv)

    with open(args.apk, 'rb') as handle:
        data = handle.read()

    try:
        certificate, scheme = signer_certificate(data)
    except SignatureError as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2

    actual = fingerprint(certificate)
    print(f'APK Signature Scheme {scheme}')
    print(f'SHA256: {actual}')

    if args.expect:
        if normalise(actual) != normalise(args.expect):
            print(
                'ERROR: the APK is not signed with the expected key.\n'
                f'  expected {normalise(args.expect)}\n'
                f'  actual   {normalise(actual)}\n'
                'Android will refuse to install this build over the previous '
                'one. The keystore in ANDROID_DEBUG_KEYSTORE_B64 was probably '
                'not the one used to sign it.',
                file=sys.stderr,
            )
            return 1
        print('OK: signed with the expected key.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
