[app]

title = TMDB Movie Recommender
package.name = tmdbmovierecommender
package.domain = org.dathaze20

source.dir = .
source.include_exts = py,png,jpg,kv,atlas
# .env has no filename "extension" for Buildozer's matcher to see, so it
# has to be listed explicitly or the packaged app won't find your API key.
source.include_patterns = .env

version = 1.0.0

# Keep this in sync with requirements.txt, with two deliberate differences:
#
#  - pillow is omitted. python-for-android has no pillow recipe, so it would
#    be resolved by pip under --only-binary=:all:, and pillow publishes no
#    py3-none-any wheel - the build fails outright. Nothing here imports PIL
#    (Kivy uses its SDL2 image provider on Android), so it is not needed.
#  - certifi is added. It is what ssl points at for HTTPS on Android, where
#    there is no system CA bundle; see the certifi block in main.py.
#  - python_dotenv is spelled with an UNDERSCORE, deliberately. Do not
#    "correct" it to python-dotenv. python-for-android compares the wheel's
#    metadata name normalised to underscores against the requirement names
#    exactly as written here. A hyphen never matches, so p4a decides the
#    package is unlisted and appends the resolved wheel URL *alongside* the
#    pin - pip then sees both "python-dotenv==1.2.2" and "python-dotenv 1.2.3
#    from <url>" and fails with ResolutionImpossible.
requirements = python3,kivy==2.3.1,requests,tmdbv3api==1.9.0,python_dotenv==1.2.2,certifi

# App needs network access to reach the TMDB API and poster CDN.
android.permissions = INTERNET

orientation = portrait
fullscreen = 0

# Reasonable, well-supported defaults for sideloading on a personal phone.
# Bump android.api to whatever Google Play currently enforces (check
# developer.android.com/google/play/requirements before ever publishing).
android.minapi = 24
android.api = 34
android.ndk_api = 24

# Required for unattended builds: without it the SDK licence prompt waits
# for input that CI can never provide, and the job hangs until it times out.
android.accept_sdk_license = True

# Placeholder branded icon/splash (dark background, gold star, purple ring
# matching the in-app theme) - swap these files for real artwork before
# building a release you intend to keep.
icon.filename = %(source.dir)s/assets/icon.png
presplash.filename = %(source.dir)s/assets/presplash.png

android.archs = arm64-v8a, armeabi-v7a

[buildozer]
log_level = 2
warn_on_root = 1
