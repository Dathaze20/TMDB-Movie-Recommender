"""Pure, framework-free helpers used by main.py.

Deliberately has no Kivy (or any GUI) import, so it can be unit tested
directly under pytest without a display/GL context - see tests/.
"""

GENRES = {
    28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy",
    80: "Crime", 99: "Documentary", 18: "Drama", 10751: "Family",
    14: "Fantasy", 36: "History", 27: "Horror", 10402: "Music",
    9648: "Mystery", 10749: "Romance", 878: "Sci-Fi", 10770: "TV Movie",
    53: "Thriller", 10752: "War", 37: "Western",
}


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
