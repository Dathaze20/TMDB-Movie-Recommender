import os
import sys
import json
import socket
import hashlib
import logging
import threading
import urllib.request
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Dict
from dotenv import load_dotenv

from kivy.config import Config
Config.set('kivy', 'keyboard_mode', 'system')

from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.metrics import dp
from kivy.properties import StringProperty, NumericProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import AsyncImage
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import ScreenManager, Screen, SlideTransition
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.utils import platform
from kivy import kivy_data_dir
from tmdbv3api import TMDb, Movie
from tmdbv3api.exceptions import TMDbException

# Kivy's default font (Roboto) has no glyphs for ★ ☆ ✕ ← ▶, so those render
# as blank boxes - DejaVuSans (also bundled with Kivy, on every platform
# including Android) does have them.
SYMBOL_FONT = os.path.join(kivy_data_dir, 'fonts', 'DejaVuSans.ttf')

# Prevent a flaky/hung mobile connection from blocking a background thread
# (and the loading popup) forever.
socket.setdefaulttimeout(15)

def _find_env_file():
    """Look for .env next to the script, in the current working directory,
    and one level up - covers the common ways an Android runner (Pydroid,
    Termux) can end up launching main.py from an unexpected working
    directory or a nested folder from a zip download."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = []
    for d in (script_dir, os.getcwd(), os.path.dirname(script_dir)):
        path = os.path.join(d, '.env')
        if path not in candidates:
            candidates.append(path)
    for path in candidates:
        if os.path.exists(path):
            return path, candidates
    return None, candidates


_script_dir = os.path.dirname(os.path.abspath(__file__))
_env_path, _env_candidates = _find_env_file()
load_dotenv(_env_path) if _env_path else load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(message)s')

api_key = os.getenv('TMDB_API_KEY')
if not api_key:
    _checked = ', '.join(_env_candidates)
    logging.error(f"TMDB_API_KEY not found. Checked for .env at: {_checked}")

tmdb = TMDb()
tmdb.api_key = api_key or ''
tmdb.wait_on_rate_limit = True

TMDB_ATTRIBUTION = "This product uses the TMDB API but is not endorsed or certified by TMDB."

BG_COLOR = (0.05, 0.05, 0.1, 1)
CARD_COLOR = (0.12, 0.12, 0.18, 1)
SURFACE_COLOR = (0.16, 0.16, 0.23, 1)
ACCENT = (0.42, 0.36, 0.91, 1)
ACCENT_GLOW = (0.55, 0.48, 1.0, 1)
TEXT_PRIMARY = (0.95, 0.95, 0.97, 1)
TEXT_MUTED = (0.52, 0.52, 0.62, 1)
GOLD = (1.0, 0.84, 0.0, 1)
SEARCH_BG = (0.1, 0.1, 0.17, 1)
ERROR_COLOR = (0.92, 0.26, 0.21, 1)
TAB_INACTIVE = (0.12, 0.12, 0.18, 0.7)

GENRES = {
    28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy",
    80: "Crime", 99: "Documentary", 18: "Drama", 10751: "Family",
    14: "Fantasy", 36: "History", 27: "Horror", 10402: "Music",
    9648: "Mystery", 10749: "Romance", 878: "Sci-Fi", 10770: "TV Movie",
    53: "Thriller", 10752: "War", 37: "Western",
}

CATEGORIES = ['Popular', 'Top Rated', 'Now Playing', 'Watchlist']


def star_text(rating):
    filled = round((rating or 0) / 2)
    return '★' * filled + '☆' * (5 - filled)


class MovieDetails:
    def __init__(self, title, overview, release_date, poster_path, movie_id,
                 vote_average=0, genre_ids=None):
        self.title = title
        self.overview = overview
        self.release_date = release_date
        self.poster_path = poster_path
        self.id = movie_id
        self.vote_average = vote_average or 0
        # tmdbv3api wraps JSON lists (even lists of plain ints) in its own
        # AsObj type, which supports iteration but not slicing - normalize
        # to a real list here so genre_text's [:3] slice always works.
        self.genre_ids = list(genre_ids) if genre_ids else []

    @property
    def year(self):
        return self.release_date[:4] if self.release_date else ''

    @property
    def genre_text(self):
        names = [GENRES.get(g, '') for g in self.genre_ids[:3]]
        return ' • '.join(n for n in names if n)

    def to_json(self):
        return {
            'id': self.id, 'title': self.title, 'overview': self.overview,
            'release_date': self.release_date, 'poster_path': self.poster_path,
            'vote_average': self.vote_average, 'genre_ids': self.genre_ids,
        }

    @classmethod
    def from_json(cls, data):
        return cls(
            title=data.get('title', ''), overview=data.get('overview', ''),
            release_date=data.get('release_date', ''), poster_path=data.get('poster_path', ''),
            movie_id=data['id'], vote_average=data.get('vote_average', 0),
            genre_ids=data.get('genre_ids', []),
        )


def fetch_movies(func, query=None, page_number=1):
    try:
        result = func(query, page=page_number) if query else func(page=page_number)
        if not result:
            return None
        out = []
        for m in result:
            out.append(MovieDetails(
                title=m.title,
                overview=getattr(m, 'overview', ''),
                release_date=getattr(m, 'release_date', ''),
                poster_path=getattr(m, 'poster_path', ''),
                movie_id=m.id,
                vote_average=getattr(m, 'vote_average', 0),
                genre_ids=getattr(m, 'genre_ids', []),
            ))
        return out
    except Exception as e:
        logging.error(f"Fetch error: {e}")
        return None


def fetch_movie_extra(movie_id):
    """Single call (append_to_response) for cast, similar movies, and trailer."""
    cast, similar, trailer_key = [], [], None
    try:
        d = Movie().details(movie_id, append_to_response='credits,similar,videos')

        credits = getattr(d, 'credits', None)
        if credits:
            for c in list(getattr(credits, 'cast', []) or [])[:8]:
                name = getattr(c, 'name', '')
                if name:
                    cast.append(name)

        sim = getattr(d, 'similar', None)
        if sim:
            for m2 in list(getattr(sim, 'results', []) or [])[:10]:
                if not getattr(m2, 'poster_path', ''):
                    continue
                similar.append(MovieDetails(
                    title=getattr(m2, 'title', ''),
                    overview=getattr(m2, 'overview', ''),
                    release_date=getattr(m2, 'release_date', ''),
                    poster_path=getattr(m2, 'poster_path', ''),
                    movie_id=m2.id,
                    vote_average=getattr(m2, 'vote_average', 0),
                    genre_ids=getattr(m2, 'genre_ids', []),
                ))

        vids = getattr(d, 'videos', None)
        if vids:
            results = list(getattr(vids, 'results', []) or [])
            for v in results:
                if getattr(v, 'site', '') == 'YouTube' and getattr(v, 'type', '') == 'Trailer':
                    trailer_key = getattr(v, 'key', None)
                    break
            if not trailer_key:
                for v in results:
                    if getattr(v, 'site', '') == 'YouTube':
                        trailer_key = getattr(v, 'key', None)
                        break
    except Exception as e:
        logging.error(f"Extra details fetch error: {e}")
    return cast, similar, trailer_key


class PosterCache:
    """Caches downloaded poster bytes on disk so relaunching the app doesn't
    re-download every poster from scratch."""
    _dir = None
    _pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='poster-cache')

    @classmethod
    def _cache_dir(cls):
        if cls._dir is None:
            app = App.get_running_app()
            base = app.user_data_dir if app else _script_dir
            cls._dir = os.path.join(base, 'poster_cache')
            os.makedirs(cls._dir, exist_ok=True)
        return cls._dir

    @classmethod
    def _local_path(cls, poster_path, size):
        name = hashlib.sha1(f"{size}/{poster_path}".encode()).hexdigest() + '.jpg'
        return os.path.join(cls._cache_dir(), name)

    @classmethod
    def source(cls, poster_path, size='w185'):
        if not poster_path:
            return ''
        local = cls._local_path(poster_path, size)
        if os.path.exists(local):
            return local
        cls._pool.submit(cls._download, poster_path, size)
        return f"https://image.tmdb.org/t/p/{size}/{poster_path}"

    @classmethod
    def _download(cls, poster_path, size):
        local = cls._local_path(poster_path, size)
        if os.path.exists(local):
            return
        try:
            url = f"https://image.tmdb.org/t/p/{size}/{poster_path}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
            tmp = local + '.tmp'
            with open(tmp, 'wb') as f:
                f.write(data)
            os.replace(tmp, local)
        except Exception as e:
            logging.debug(f"Poster cache skip: {e}")


def open_external_url(url):
    try:
        if platform == 'android':
            from jnius import autoclass, cast
            Intent = autoclass('android.content.Intent')
            Uri = autoclass('android.net.Uri')
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
            activity = cast('android.app.Activity', PythonActivity.mActivity)
            activity.startActivity(intent)
        else:
            webbrowser.open(url)
    except Exception as e:
        logging.error(f"Could not open URL: {e}")


class MovieCard(ButtonBehavior, BoxLayout):
    def __init__(self, movie, **kwargs):
        super().__init__(orientation='vertical', spacing=0, padding=0, **kwargs)
        self.movie_id = movie.id
        self.size_hint_y = None

        with self.canvas.before:
            Color(*CARD_COLOR)
            self._card_bg = RoundedRectangle(
                pos=self.pos, size=self.size, radius=[dp(10)]
            )
        self.bind(
            pos=lambda i, v: setattr(i._card_bg, 'pos', v),
            size=lambda i, v: setattr(i._card_bg, 'size', v),
        )

        poster_url = PosterCache.source(movie.poster_path, 'w185')
        self.poster = AsyncImage(
            source=poster_url, size_hint=(1, None),
            allow_stretch=True, keep_ratio=True,
        )
        self.add_widget(self.poster)

        info = BoxLayout(
            orientation='vertical', size_hint_y=None, height=dp(50),
            padding=[dp(5), dp(3)],
        )

        title_lbl = Label(
            text=movie.title, font_size='11sp', color=TEXT_PRIMARY,
            halign='left', valign='middle',
            shorten=True, shorten_from='right', size_hint_y=0.5,
        )
        title_lbl.bind(size=lambda i, s: setattr(i, 'text_size', s))

        bottom_row = BoxLayout(size_hint_y=0.5)

        score = f"{movie.vote_average:.1f}" if movie.vote_average else ''
        stars_lbl = Label(
            text=f"{star_text(movie.vote_average)} {score}",
            font_size='9sp', color=GOLD, font_name=SYMBOL_FONT,
            halign='left', valign='middle', size_hint_x=0.72,
        )
        stars_lbl.bind(size=lambda i, s: setattr(i, 'text_size', s))

        year_lbl = Label(
            text=movie.year, font_size='9sp', color=TEXT_MUTED,
            halign='right', valign='middle', size_hint_x=0.28,
        )
        year_lbl.bind(size=lambda i, s: setattr(i, 'text_size', s))

        bottom_row.add_widget(stars_lbl)
        bottom_row.add_widget(year_lbl)
        info.add_widget(title_lbl)
        info.add_widget(bottom_row)
        self.add_widget(info)

        self.bind(size=self._resize)

    def _resize(self, *args):
        h = self.width * 1.5
        self.poster.height = h
        self.height = h + dp(50)


class SearchBar(BoxLayout):
    search_text = StringProperty('')

    def __init__(self, **kwargs):
        super().__init__(
            orientation='horizontal', size_hint_y=None, height=dp(46),
            spacing=dp(6), padding=[dp(4), 0], **kwargs,
        )
        self.register_event_type('on_search')

        with self.canvas.before:
            Color(*SEARCH_BG)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(14)])
        self.bind(
            pos=lambda i, v: setattr(i._bg, 'pos', v),
            size=lambda i, v: setattr(i._bg, 'size', v),
        )

        self.input = TextInput(
            hint_text='Search movies...',
            hint_text_color=(0.4, 0.4, 0.52, 1),
            multiline=False, size_hint_x=0.82,
            background_color=(0, 0, 0, 0),
            foreground_color=TEXT_PRIMARY,
            cursor_color=ACCENT_GLOW,
            padding=[dp(14), dp(12)],
            font_size='15sp',
        )
        clear = Button(
            text='✕', size_hint_x=0.18, font_name=SYMBOL_FONT,
            background_normal='',
            background_color=(*ACCENT[:3], 0.85),
            color=TEXT_PRIMARY, font_size='18sp',
        )

        self.add_widget(self.input)
        self.add_widget(clear)

        clear.bind(on_release=self._clear)
        self.input.bind(text=self._text_changed)
        self.input.bind(on_text_validate=self._submit)

    def _text_changed(self, inst, val):
        self.search_text = val

    def _clear(self, *a):
        self.input.text = ''
        self.search_text = ''
        self.dispatch('on_search')

    def _submit(self, *a):
        self.dispatch('on_search')

    def on_search(self):
        pass


class CategoryBar(BoxLayout):
    active = StringProperty('Popular')

    def __init__(self, **kwargs):
        super().__init__(
            orientation='horizontal', size_hint_y=None, height=dp(38),
            spacing=dp(4), padding=[dp(2), dp(2)], **kwargs,
        )
        self.register_event_type('on_category')
        self._btns = {}

        for name in CATEGORIES:
            btn = Button(
                text=name, background_normal='',
                background_color=ACCENT if name == 'Popular' else TAB_INACTIVE,
                color=TEXT_PRIMARY, font_size='11.5sp', bold=(name == 'Popular'),
            )
            btn.bind(on_release=lambda inst, n=name: self._pick(n))
            self._btns[name] = btn
            self.add_widget(btn)

    def _pick(self, name):
        if name == self.active:
            return
        self.active = name
        for n, b in self._btns.items():
            b.background_color = ACCENT if n == name else TAB_INACTIVE
            b.bold = (n == name)
        self.dispatch('on_category', name)

    def on_category(self, *a):
        pass


class MoviePosterApp(App):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.movie_cache: Dict[int, MovieDetails] = {}
        self.favorites: Dict[int, MovieDetails] = {}
        self.fav_file = None
        self.loading_popup = None
        self.error_label = None
        self.grid = None
        self.search_bar = None
        self.title_label = None
        self.cat_bar = None
        self.current_cat = 'Popular'
        self._search_query = None
        self.load_generation = 0
        self._current_page = 1
        self._has_more = True
        self._loading_more = False
        self._detail_token = 0
        self._detail_body = None

    def build(self):
        Window.clearcolor = BG_COLOR
        Window.bind(on_keyboard=self._on_key)
        self._load_favorites()

        sm = ScreenManager(transition=SlideTransition())
        self.sm = sm
        self.main_scr = Screen(name='Main')
        self.detail_scr = Screen(name='Detail')

        root = BoxLayout(orientation='vertical', padding=dp(6), spacing=dp(5))

        title_bar = BoxLayout(size_hint_y=None, height=dp(50), padding=[dp(14), 0], spacing=dp(8))
        with title_bar.canvas.before:
            Color(*CARD_COLOR)
            title_bar._bg = RoundedRectangle(
                pos=title_bar.pos, size=title_bar.size, radius=[dp(14)]
            )
        title_bar.bind(
            pos=lambda i, v: setattr(i._bg, 'pos', v),
            size=lambda i, v: setattr(i._bg, 'size', v),
        )
        self.title_label = Label(
            text='Popular Movies', font_size='20sp', bold=True,
            color=TEXT_PRIMARY, halign='left',
        )
        self.title_label.bind(size=lambda i, s: setattr(i, 'text_size', s))
        about_btn = Button(
            text='i', size_hint=(None, None), size=(dp(34), dp(34)),
            background_normal='', background_color=TAB_INACTIVE,
            color=TEXT_PRIMARY, font_size='16sp', bold=True, italic=True,
        )
        about_btn.bind(on_release=self._show_about)
        title_bar.add_widget(self.title_label)
        title_bar.add_widget(about_btn)
        root.add_widget(title_bar)

        self.search_bar = SearchBar()
        self.search_bar.bind(on_search=self._on_search)
        root.add_widget(self.search_bar)

        self.cat_bar = CategoryBar()
        self.cat_bar.bind(on_category=self._on_category)
        root.add_widget(self.cat_bar)

        self.error_label = Label(
            text='', color=ERROR_COLOR, size_hint_y=None,
            height=dp(0), font_size='13sp', font_name=SYMBOL_FONT,
            halign='center', valign='middle',
        )
        self.error_label.bind(
            width=lambda i, w: setattr(i, 'text_size', (w - dp(12), None)),
            texture_size=lambda i, s: setattr(i, 'height', s[1] + dp(10) if i.text else 0),
        )
        root.add_widget(self.error_label)

        self.scroll = ScrollView(
            size_hint=(1, 1), do_scroll_x=False,
            bar_width=dp(3), bar_color=(*ACCENT[:3], 0.4),
        )
        self.scroll.bind(scroll_y=self._on_scroll)
        self.grid = GridLayout(
            cols=3, spacing=dp(5), padding=dp(3), size_hint_y=None,
        )
        self.grid.bind(minimum_height=self.grid.setter('height'))
        self.scroll.add_widget(self.grid)
        root.add_widget(self.scroll)

        self.main_scr.add_widget(root)
        sm.add_widget(self.main_scr)
        sm.add_widget(self.detail_scr)

        if not api_key:
            checked = ' OR '.join(_env_candidates)
            self._show_error(f"TMDB_API_KEY missing. Checked for a .env file at: {checked}")
            return sm

        self._show_loading()
        gen = self.load_generation
        threading.Thread(target=self._load_cat, args=('Popular', gen), daemon=True).start()
        return sm

    # -- favorites / watchlist -------------------------------------------------

    def _load_favorites(self):
        self.fav_file = os.path.join(self.user_data_dir, 'favorites.json')
        try:
            if os.path.exists(self.fav_file):
                with open(self.fav_file, 'r') as f:
                    raw = json.load(f)
                for item in raw:
                    mv = MovieDetails.from_json(item)
                    self.favorites[mv.id] = mv
        except Exception as e:
            logging.error(f"Favorites load error: {e}")

    def _save_favorites(self):
        try:
            raw = [mv.to_json() for mv in self.favorites.values()]
            with open(self.fav_file, 'w') as f:
                json.dump(raw, f)
        except Exception as e:
            logging.error(f"Favorites save error: {e}")

    def is_favorite(self, movie_id):
        return movie_id in self.favorites

    def toggle_favorite(self, movie):
        if movie.id in self.favorites:
            del self.favorites[movie.id]
        else:
            self.favorites[movie.id] = movie
        self._save_favorites()

    # -- navigation / category / search -----------------------------------------

    def _reset_pagination(self):
        self._current_page = 1
        self._has_more = True
        self._loading_more = False

    def _show_watchlist(self):
        self._has_more = False
        if not self.favorites:
            self._show_error("Your watchlist is empty. Open a movie and tap ☆ to add it.")
            return
        for mv in self.favorites.values():
            self.movie_cache[mv.id] = mv
            self._add_card(mv)

    def _on_category(self, inst, cat):
        self.load_generation += 1
        gen = self.load_generation
        self.current_cat = cat
        self.search_bar.input.text = ''
        self.search_bar.search_text = ''
        self._search_query = None
        self.title_label.text = 'My Watchlist' if cat == 'Watchlist' else f'{cat} Movies'
        self._clear_error()
        self._clear_grid()
        self._reset_pagination()

        if cat == 'Watchlist':
            self._show_watchlist()
            return

        self._show_loading()
        threading.Thread(target=self._load_cat, args=(cat, gen), daemon=True).start()

    def _on_search(self, *a):
        q = self.search_bar.search_text.strip()
        self.load_generation += 1
        gen = self.load_generation
        self._clear_error()
        self._clear_grid()
        self._reset_pagination()

        if not q:
            self._search_query = None
            cat = self.cat_bar.active
            self.current_cat = cat
            self.title_label.text = 'My Watchlist' if cat == 'Watchlist' else f'{cat} Movies'
            if cat == 'Watchlist':
                self._show_watchlist()
                return
            self._show_loading()
            threading.Thread(target=self._load_cat, args=(cat, gen), daemon=True).start()
            return

        self._search_query = q
        self.title_label.text = f'Search: {q}'
        self._show_loading()
        threading.Thread(target=self._do_search, args=(q, gen), daemon=True).start()

    def _cat_func(self, cat):
        m = Movie()
        if cat == 'Top Rated':
            return m.top_rated
        if cat == 'Now Playing':
            return m.now_playing
        return m.popular

    def _load_cat(self, cat, gen):
        try:
            func = self._cat_func(cat)
            first = fetch_movies(func, page_number=1)
            if gen != self.load_generation:
                return
            if not first:
                self._show_error("Could not load movies. Check your connection.")
                self._hide_loading()
                self._has_more = False
                return
            for mv in first:
                self.movie_cache[mv.id] = mv
                self._add_card(mv)
            self._hide_loading()
            self._current_page = 1
            self._has_more = True
        except Exception as e:
            logging.error(f"Load error: {e}")
            self._show_error("Could not load movies. Check your connection.")
            self._hide_loading()
            self._has_more = False

    def _do_search(self, query, gen):
        try:
            first = fetch_movies(Movie().search, query, 1)
            if gen != self.load_generation:
                return
            if not first:
                self._show_error("No movies found.")
                self._hide_loading()
                self._has_more = False
                return
            for mv in first:
                self.movie_cache[mv.id] = mv
                self._add_card(mv)
            self._hide_loading()
            self._current_page = 1
            self._has_more = True
        except Exception as e:
            logging.error(f"Search error: {e}")
            self._show_error("Search failed. Check your connection.")
            self._hide_loading()
            self._has_more = False

    # -- infinite scroll ----------------------------------------------------

    def _on_scroll(self, instance, value):
        if value <= 0.15:
            self._load_more()

    def _load_more(self):
        if self._loading_more or not self._has_more or self.current_cat == 'Watchlist':
            return
        self._loading_more = True
        gen = self.load_generation
        threading.Thread(target=self._fetch_more, args=(gen,), daemon=True).start()

    def _fetch_more(self, gen):
        try:
            next_page = self._current_page + 1
            if next_page > 20:
                self._has_more = False
                return
            if self._search_query:
                more = fetch_movies(Movie().search, self._search_query, next_page)
            else:
                func = self._cat_func(self.current_cat)
                more = fetch_movies(func, page_number=next_page)
            if gen != self.load_generation:
                return
            if not more:
                self._has_more = False
                return
            self._current_page = next_page
            for mv in more:
                self.movie_cache[mv.id] = mv
                self._add_card(mv)
        except Exception as e:
            logging.error(f"Load more error: {e}")
        finally:
            self._loading_more = False

    # -- widget helpers -------------------------------------------------------

    @mainthread
    def _add_card(self, movie):
        if not self.grid or not movie.poster_path:
            return
        card = MovieCard(movie)
        card.bind(on_release=self._open_detail)
        self.grid.add_widget(card)

    @mainthread
    def _show_error(self, msg):
        if self.error_label:
            self.error_label.text = msg

    @mainthread
    def _clear_error(self):
        if self.error_label:
            self.error_label.text = ''
            self.error_label.height = 0
            self.error_label.height = dp(0)

    @mainthread
    def _clear_grid(self):
        if self.grid:
            self.grid.clear_widgets()

    @mainthread
    def _show_loading(self):
        self.loading_popup = Popup(
            title='', separator_height=0,
            content=Label(text='Loading...', color=TEXT_PRIMARY, font_size='15sp'),
            size_hint=(None, None), size=(dp(150), dp(90)),
            auto_dismiss=False,
            background_color=(*CARD_COLOR[:3], 0.95),
        )
        self.loading_popup.open()

    @mainthread
    def _hide_loading(self):
        if self.loading_popup:
            self.loading_popup.dismiss()

    def _show_about(self, *a):
        content = BoxLayout(orientation='vertical', padding=dp(16), spacing=dp(12))
        lbl = Label(
            text=TMDB_ATTRIBUTION, color=TEXT_PRIMARY, font_size='13sp',
            halign='center', valign='middle', size_hint_y=1,
            text_size=(dp(280), None),
        )
        content.add_widget(lbl)
        close = Button(
            text='Close', size_hint_y=None, height=dp(40),
            background_normal='', background_color=ACCENT, color=TEXT_PRIMARY,
        )
        content.add_widget(close)
        popup = Popup(
            title='About', size_hint=(None, None), size=(dp(300), dp(200)),
            content=content, background_color=(*CARD_COLOR[:3], 0.98),
        )
        close.bind(on_release=popup.dismiss)
        popup.open()

    def _on_key(self, window, key, *args):
        if key == 27:
            if self.sm.current == 'Detail':
                self._go_back()
                return True
            return False
        return False

    # -- detail screen --------------------------------------------------------

    def _open_detail(self, inst):
        mid = getattr(inst, 'movie_id', None)
        if mid is None:
            return
        movie = self.movie_cache.get(mid)
        self._render_detail(movie)

    def _render_detail(self, movie):
        if not movie:
            return
        self._detail_token += 1
        token = self._detail_token

        self.detail_scr.clear_widgets()

        page = BoxLayout(orientation='vertical')
        with page.canvas.before:
            Color(*BG_COLOR)
            page._bg = Rectangle(pos=page.pos, size=page.size)
        page.bind(
            pos=lambda i, v: setattr(i._bg, 'pos', v),
            size=lambda i, v: setattr(i._bg, 'size', v),
        )

        top = BoxLayout(size_hint_y=None, height=dp(48), padding=[dp(6), dp(4)], spacing=dp(6))
        with top.canvas.before:
            Color(*CARD_COLOR)
            top._bg = Rectangle(pos=top.pos, size=top.size)
        top.bind(
            pos=lambda i, v: setattr(i._bg, 'pos', v),
            size=lambda i, v: setattr(i._bg, 'size', v),
        )

        back = Button(
            text='← Back', size_hint_x=0.22, font_name=SYMBOL_FONT,
            background_normal='', background_color=ACCENT,
            color=TEXT_PRIMARY, font_size='13sp', bold=True,
        )
        back.bind(on_release=self._go_back)

        ttl = Label(
            text=movie.title, font_size='15sp', bold=True,
            color=TEXT_PRIMARY, shorten=True, shorten_from='right',
            halign='center', size_hint_x=0.62,
        )
        ttl.bind(size=lambda i, s: setattr(i, 'text_size', s))

        fav_btn = Button(
            text=('★' if self.is_favorite(movie.id) else '☆'), size_hint_x=0.16,
            font_name=SYMBOL_FONT,
            background_normal='', background_color=ACCENT,
            color=GOLD, font_size='18sp', bold=True,
        )

        def _toggle_fav(btn_inst):
            self.toggle_favorite(movie)
            btn_inst.text = '★' if self.is_favorite(movie.id) else '☆'

        fav_btn.bind(on_release=_toggle_fav)

        top.add_widget(back)
        top.add_widget(ttl)
        top.add_widget(fav_btn)
        page.add_widget(top)

        scroll = ScrollView(size_hint=(1, 1), do_scroll_x=False)
        body = BoxLayout(
            orientation='vertical', size_hint_y=None,
            padding=dp(14), spacing=dp(10),
        )
        body.bind(minimum_height=body.setter('height'))

        if movie.poster_path:
            body.add_widget(AsyncImage(
                source=PosterCache.source(movie.poster_path, 'w500'),
                size_hint=(1, None), height=dp(380),
                allow_stretch=True, keep_ratio=True,
            ))

        body.add_widget(self._label(
            movie.title, '22sp', TEXT_PRIMARY, bold=True, height=dp(36),
        ))

        stars = star_text(movie.vote_average)
        score = f"{movie.vote_average:.1f}/10" if movie.vote_average else 'N/A'
        body.add_widget(self._label(f"{stars}  {score}", '16sp', GOLD, height=dp(28), font_name=SYMBOL_FONT))

        meta = []
        if movie.year:
            meta.append(movie.year)
        if movie.genre_text:
            meta.append(movie.genre_text)
        if meta:
            body.add_widget(self._label(' | '.join(meta), '13sp', TEXT_MUTED, height=dp(22)))

        sep = Widget(size_hint_y=None, height=dp(1))
        with sep.canvas:
            Color(*SURFACE_COLOR)
            sep._r = Rectangle(pos=sep.pos, size=sep.size)
        sep.bind(
            pos=lambda i, v: setattr(i._r, 'pos', v),
            size=lambda i, v: setattr(i._r, 'size', v),
        )
        body.add_widget(sep)

        body.add_widget(self._label('Overview', '16sp', TEXT_PRIMARY, bold=True, height=dp(28)))

        if movie.overview:
            ov = Label(
                text=movie.overview, font_size='14sp',
                color=(0.78, 0.78, 0.84, 1), size_hint_y=None,
                halign='left', valign='top',
                text_size=(Window.width - dp(34), None),
            )
            ov.bind(texture_size=ov.setter('size'))
            body.add_widget(ov)

        scroll.add_widget(body)
        page.add_widget(scroll)

        self.detail_scr.add_widget(page)
        self.sm.transition.direction = 'left'
        self.sm.current = 'Detail'

        self._detail_body = body
        threading.Thread(target=self._load_extra_details, args=(movie.id, token), daemon=True).start()

    def _load_extra_details(self, movie_id, token):
        cast, similar, trailer_key = fetch_movie_extra(movie_id)
        if token != self._detail_token:
            return
        self._apply_extra_details(cast, similar, trailer_key)

    @mainthread
    def _apply_extra_details(self, cast, similar, trailer_key):
        body = self._detail_body
        if not body:
            return

        if trailer_key:
            trailer_btn = Button(
                text='▶  Watch Trailer', size_hint_y=None, height=dp(42),
                font_name=SYMBOL_FONT,
                background_normal='', background_color=ERROR_COLOR,
                color=TEXT_PRIMARY, font_size='14sp', bold=True,
            )
            trailer_btn.bind(
                on_release=lambda i: open_external_url(f"https://www.youtube.com/watch?v={trailer_key}")
            )
            body.add_widget(trailer_btn)

        if cast:
            body.add_widget(self._label('Cast', '16sp', TEXT_PRIMARY, bold=True, height=dp(28)))
            cast_scroll = ScrollView(
                size_hint=(1, None), height=dp(30),
                do_scroll_x=True, do_scroll_y=False, bar_width=0,
            )
            cast_box = BoxLayout(size_hint=(None, 1), spacing=dp(14))
            cast_box.bind(minimum_width=cast_box.setter('width'))
            for name in cast:
                cast_box.add_widget(Label(
                    text=name, font_size='12sp', color=TEXT_MUTED,
                    size_hint_x=None, width=dp(130),
                ))
            cast_scroll.add_widget(cast_box)
            body.add_widget(cast_scroll)

        if similar:
            body.add_widget(self._label('Similar Movies', '16sp', TEXT_PRIMARY, bold=True, height=dp(28)))
            sim_scroll = ScrollView(
                size_hint=(1, None), height=dp(215),
                do_scroll_x=True, do_scroll_y=False, bar_width=0,
            )
            sim_box = BoxLayout(size_hint=(None, 1), spacing=dp(8))
            sim_box.bind(minimum_width=sim_box.setter('width'))
            for mv in similar:
                self.movie_cache[mv.id] = mv
                thumb = MovieCard(mv)
                thumb.size_hint_x = None
                thumb.width = dp(110)
                thumb.bind(on_release=lambda inst: self._render_detail(self.movie_cache.get(inst.movie_id)))
                sim_box.add_widget(thumb)
            sim_scroll.add_widget(sim_box)
            body.add_widget(sim_scroll)

        body.add_widget(Widget(size_hint_y=None, height=dp(20)))

    def _label(self, text, size, color, bold=False, height=None, font_name=None):
        lbl = Label(
            text=text, font_size=size, color=color, bold=bold,
            size_hint_y=None, height=height if height is not None else dp(30),
            halign='left', text_size=(Window.width - dp(34), None),
            font_name=font_name or 'Roboto',
        )
        return lbl

    def _go_back(self, *a):
        self.sm.transition.direction = 'right'
        self.sm.current = 'Main'


if __name__ == '__main__':
    MoviePosterApp().run()
