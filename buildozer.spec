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

# Keep this in sync with requirements.txt.
requirements = python3,kivy==2.3.1,requests,tmdbv3api==1.9.0,python-dotenv==1.2.2,pillow==12.3.0

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

# Placeholder branded icon/splash (dark background, gold star, purple ring
# matching the in-app theme) - swap these files for real artwork before
# building a release you intend to keep.
icon.filename = %(source.dir)s/assets/icon.png
presplash.filename = %(source.dir)s/assets/presplash.png

android.archs = arm64-v8a, armeabi-v7a

[buildozer]
log_level = 2
warn_on_root = 1
