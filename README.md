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
3.  **Set Up Environment Variables:**
    *   Copy `.env.example` to `.env` in the project's root directory.
        ```bash
        cp .env.example .env
        ```
    *   Add your TMDB API key to the `.env` file:
        ```env
        TMDB_API_KEY=YOUR_TMDB_API_KEY
        ```
4.  **Run the App:**
    ```bash
    python main.py
    ```

## Building an Android APK

This repo includes a `buildozer.spec` so you can build an installable APK and side-load it onto your own phone.

1.  On Linux (or WSL), install [Buildozer](https://buildozer.readthedocs.io/) and its Android build dependencies.
2.  Make sure your real `.env` (with your TMDB API key) exists in the project root — `buildozer.spec` bundles it into the app so it works on-device. This means your API key is embedded in the built APK; that's an accepted trade-off for personal/side-loaded use, not something you'd want for a public Play Store release (see `buildozer.spec` comments).
3.  Build and install to a connected/adb-authorized phone:
    ```bash
    buildozer -v android debug deploy run
    ```
4.  The first build downloads the Android SDK/NDK and will take a while. Subsequent builds are much faster.

Before ever publishing to Google Play, bump `android.api` in `buildozer.spec` to whatever target level Play currently requires, add real `icon.png`/`presplash.png` assets, and write a privacy policy (the app sends network requests to TMDB but stores no personal data locally beyond your own watchlist).

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
