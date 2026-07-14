from movie_utils import GENRES, MovieDetails, star_text


def test_star_text_full_and_empty():
    assert star_text(10) == '★★★★★'
    assert star_text(0) == '☆☆☆☆☆'
    assert star_text(None) == '☆☆☆☆☆'


def test_star_text_rounds_half_to_even():
    # Python's round() uses banker's rounding: 7/2 = 3.5 rounds up to 4
    # (4 is even), but 5/2 = 2.5 rounds down to 2 (2 is even).
    assert star_text(7) == '★★★★☆'
    assert star_text(5) == '★★☆☆☆'


def _movie(**overrides):
    defaults = dict(
        title='Test Movie', overview='An overview', release_date='2024-03-15',
        poster_path='/abc.jpg', movie_id=42, vote_average=8.4, genre_ids=[28, 12, 16, 35],
    )
    defaults.update(overrides)
    return MovieDetails(**defaults)


def test_year_extracts_four_digit_year():
    assert _movie().year == '2024'


def test_year_is_empty_when_no_release_date():
    assert _movie(release_date='').year == ''


def test_genre_text_joins_first_three_known_genres():
    m = _movie(genre_ids=[28, 12, 16, 35])
    assert m.genre_text == 'Action • Adventure • Animation'


def test_genre_text_skips_unknown_genre_ids():
    m = _movie(genre_ids=[999999, 28])
    assert m.genre_text == 'Action'


def test_genre_text_empty_when_no_genres():
    assert _movie(genre_ids=[]).genre_text == ''


def test_to_json_round_trips_through_from_json():
    original = _movie()
    restored = MovieDetails.from_json(original.to_json())
    assert restored.to_json() == original.to_json()


def test_from_json_defaults_missing_optional_fields():
    restored = MovieDetails.from_json({'id': 7})
    assert restored.title == ''
    assert restored.vote_average == 0
    assert restored.genre_ids == []
    assert restored.id == 7


def test_genres_dict_has_no_duplicate_names():
    assert len(GENRES) == len(set(GENRES.values()))
