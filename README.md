# TMDB Movie Recommender App

This is a movie recommendation app built using Python and Kivy, leveraging the TMDB API. It allows users to browse popular movies, search for specific titles, save favorites to a watchlist, and view detailed information including cast, similar movies, and trailers.

## Features

*   **Browse Movies:**
    *   Popular, Top Rated, and Now Playing tabs, each with infinite-scroll pagination (loads more as you scroll instead of all at once).
    *   Presents movies with their posters, star ratings, and release year.

*   **Search:**
    *   Search for movies by title, with the same infinite-scroll pagination as browsing.
    *   Shows an error when no movies are found.

*   **Watchlist:**
    *   Tap ☆ on any movie's detail screen to save it to a local Watchlist tab.
    *   Watchlist persists across app restarts (stored locally, no account needed).

*   **Movie Details:**
    *   Title, overview, rating, genres, and a large poster image.
    *   Cast list and similar movies (tap to jump straight to that movie's details).
    *   Watch Trailer button that opens the YouTube trailer, when one is available.

*   **Performance:**
    *   Posters are cached to disk after first download, so relaunching the app doesn't re-fetch images you've already seen.
    *   Grid thumbnails request a smaller image size than the full detail view, to save bandwidth and memory on phones.
    *   Network calls have a timeout so a bad connection can't hang the app indefinitely; TMDB rate limiting is handled automatically.

*   **Android:**
    *   Hardware/gesture back button navigates from the detail screen back to the main list instead of exiting the app.
    *   `buildozer.spec` included for building an installable APK (see below).

*   **Error Handling:**
    *   All errors are shown on screen rather than only in the console/log.

*   **Attribution:**
    *   Tap the ⓘ button for the required TMDB attribution notice.

## How to Use (Desktop)

1.  **Clone the Repository:**
    ```bash
    git clone [repository URL]
    cd [project directory]
    ```
2.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
3.  **Set Up Your TMDB API Key:**

    The app ships with **no key of its own**. On first launch it shows a setup
    screen that walks you through getting one and stores it on the device.

    For development you can skip that screen by supplying a key up front:
    *   Copy `.env.example` to `.env` in the project's root directory.
        ```bash
        cp .env.example .env
        ```
    *   Add your TMDB API key to the `.env` file:
        ```env
        TMDB_API_KEY=YOUR_TMDB_API_KEY
        ```

    Resolution order is: the `TMDB_API_KEY` environment variable, then `.env`,
    then whatever key you saved in the app. `.env` is gitignored and must
    never be committed.
4.  **Run the App:**
    ```bash
    python main.py
    ```

## Building an Android APK

### The easy way: GitHub Actions

`.github/workflows/build-apk.yml` builds the APK for you, so you don't need a
PC at all. It runs on every push to `main`, or on demand:

1.  **Actions → Build Android APK → Run workflow.**
2.  Wait. The first run takes roughly an hour — it downloads the Android
    SDK/NDK and builds both CPU architectures. Later runs are cached and much
    faster.
3.  Download the `tmdb-movie-recommender-apk` artifact from the finished run,
    unzip it, move the `.apk` to your phone and tap it. Android will ask you
    to allow installing from unknown sources — expected for a sideloaded app.

Optionally set a `TMDB_API_KEY` repository secret (**Settings → Secrets and
variables → Actions**) and it is bundled as `.env`, so the APK starts already
configured. Without it the app opens its setup screen and asks for a key.

### Building locally instead

Requires Linux or WSL; buildozer cannot run on Android itself.

1.  Install [Buildozer](https://buildozer.readthedocs.io/) and its Android
    build dependencies.
2.  Optionally put your own `.env` in the project root — `buildozer.spec`
    bundles it, so the APK starts configured. Note this puts the key inside
    the APK, which is fine for your own sideloaded build but not for anything
    you share. Leave it out and the app asks for a key on first launch
    instead, storing it on the device only.
3.  Build and install to a connected, adb-authorized phone:
    ```bash
    buildozer -v android debug deploy run
    ```

### Notes on the build config

-   `pillow` is in `requirements.txt` but deliberately **not** in
    `buildozer.spec`. python-for-android has no pillow recipe, so it would be
    resolved by pip under `--only-binary=:all:`, and pillow ships no
    `py3-none-any` wheel — the build fails. Nothing imports PIL (Kivy uses its
    SDL2 image provider on Android), so it isn't needed there.
-   `certifi` **is** in `buildozer.spec`. Android has no system CA bundle that
    Python's `ssl` can find, so without it every HTTPS call fails on-device
    with `CERTIFICATE_VERIFY_FAILED`. Shipping `certifi` is necessary but not
    sufficient: `nettls.py` has to install it as the process default, because
    `urlopen` caches one opener whose `HTTPSHandler` captures its SSL context
    at construction. Setting `SSL_CERT_FILE` alone does not reach it, which is
    exactly how the first release failed on a phone while passing CI.
-   `android.accept_sdk_license = True` is required for unattended builds;
    without it CI hangs on a licence prompt it can never answer.

### Signing

Android refuses to install an APK over one signed by a different key. Every CI
runner generates its own throwaway debug keystore, so for the first few
releases each build had a different signature and every update meant
uninstalling the app first — losing the local watchlist.

The workflow now restores a fixed keystore from the
`ANDROID_DEBUG_KEYSTORE_B64` repository secret (**Settings → Secrets and
variables → Actions**), base64-encoded, with alias `androiddebugkey` and
store/key password `android` — the standard Android debug credentials, which
is what the Gradle debug signing config expects.

To generate one:

```bash
keytool -genkeypair -v -keystore debug.keystore \
  -alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10950 \
  -storepass android -keypass android \
  -dname "CN=Android Debug, O=Android, C=US"
base64 -w 0 debug.keystore      # paste this into the secret
```

Notes:

-   **The build fails if the secret is missing**, rather than falling back to a
    random key and producing an APK that will not install over the last one.
-   After building, `tools/apk_signature.py` reads the signer certificate back
    out of the APK and compares its SHA-256 to the keystore's. A silent
    fallback would otherwise pass CI and only fail on a phone.
-   This is a **debug** key. It carries no trust, cannot publish to Google
    Play, and exists only to keep successive builds installable over each
    other. Publishing to Play needs a real upload key, kept somewhere safer.
-   It still lives in a secret rather than the repo, so the repository holds no
    credential-shaped file. `*.keystore`, `*.jks` and `*.p12` are gitignored
    and a test asserts none is ever tracked.

Before ever publishing to Google Play, bump `android.api` in `buildozer.spec` to whatever target level Play currently requires, add real `icon.png`/`presplash.png` assets, and write a privacy policy (the app sends network requests to TMDB but stores no personal data locally beyond your own watchlist).

## Tests

The pure data/formatting logic (star ratings, genre lookup, year parsing,
watchlist JSON serialization) lives in `movie_utils.py`, which has no Kivy
import, so it's unit tested directly with pytest — no display or GL context
needed:

```bash
pip install -r requirements-dev.txt
pytest -v
```

CI (`.github/workflows/test.yml`) runs this on every push and pull request.

## Technologies Used

*   **Python:** Programming language.
*   **Kivy:** For creating the cross platform UI.
*   **tmdbv3api:** TMDB API library for accessing movie data.
*   **python-dotenv:** To securely manage API key and other environment variables.
*   **Pillow:** Image loading support (also used by Kivy/python-for-android on Android builds).
*   **Buildozer:** Packages the app into an Android APK.
*   **logging:** To log issues and events that happen within the program.

## Attribution

This product uses the TMDB API but is not endorsed or certified by TMDB.

## Future Improvements

*   **Recommendation System:** Personalized recommendations based on watchlist/viewing history.
*   **Improved Search:** Filter by genre, actor, and director.
*   **User Authentication:** Sync watchlist across devices via TMDB account login.
*   **Reviews:** Show user reviews alongside ratings.
*   **RecycleView:** Migrate the poster grid to `RecycleView` if the list ever needs to scale well beyond a few hundred items.
*   **API key protection:** Route TMDB calls through a small serverless proxy instead of embedding the key client-side, if this is ever published.

## License

This project is licensed under the [MIT License](LICENSE).
