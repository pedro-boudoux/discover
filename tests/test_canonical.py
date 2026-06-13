"""
Tier-1 unit tests for canonical identity (issue #11 — exclude duplicate tracks).
No database required: these are pure string transforms.

The contract: cosmetic, same-recording qualifiers (clean / explicit / remastered
/ bonus track / trailing feat.) fold to one canonical_key, while sonically
distinct editions (live / acoustic / remix / demo / instrumental) and genuinely
different songs (numbered / multi-part tracks) stay separate.
"""

import pytest

from app.services.embeddings import (
    canonical_title,
    make_canonical_key,
    make_track_id,
)


# ---------------------------------------------------------------------------
# canonical_title — strips only same-recording cosmetic suffixes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("Song", "Song"),
    ("Song (Clean)", "Song"),
    ("Song (Explicit)", "Song"),
    ("Song [Dirty]", "Song"),
    ("Song (Remastered)", "Song"),
    ("Song (Remastered 2011)", "Song"),
    ("Song - Remastered 2009", "Song"),
    ("Song (Radio Edit)", "Song"),
    ("Song (Single Version)", "Song"),
    ("Song (Album Version)", "Song"),
    ("Song (Bonus Track)", "Song"),
    ("Song (feat. Drake)", "Song"),
    ("Song (Remastered) (Bonus Track)", "Song"),  # stacked suffixes
    ("  Song (Explicit)  ", "Song"),               # surrounding whitespace
])
def test_strips_cosmetic_suffixes(raw, expected):
    assert canonical_title(raw) == expected


@pytest.mark.parametrize("raw", [
    "Song (Live)",
    "Song (Acoustic)",
    "Song (Remix)",
    "Song (Demo)",
    "Song (Instrumental)",
    "Untitled 02",
    "Untitled 03",
    "Pt. 1",
    "Pt. 2",
    "Act II",
])
def test_keeps_sonically_distinct_editions(raw):
    # These must pass through untouched — they are different recordings/songs.
    assert canonical_title(raw) == raw.strip()


def test_never_returns_empty():
    # A title that is itself only a qualifier must not be stripped to nothing.
    assert canonical_title("(Remastered)") == "(Remastered)"


# ---------------------------------------------------------------------------
# make_canonical_key — folds variants, separates distinct songs/artists
# ---------------------------------------------------------------------------

def test_variants_share_a_key():
    base = make_canonical_key("Kendrick Lamar", "DNA.")
    assert make_canonical_key("Kendrick Lamar", "DNA. (Explicit)") == base
    assert make_canonical_key("kendrick lamar", "DNA. (Clean)") == base
    assert make_canonical_key("Kendrick Lamar", "DNA. - Remastered 2017") == base


def test_numbered_tracks_do_not_collide():
    # The exact failure mode fuzzy matching gets wrong — these stay distinct.
    assert make_canonical_key("Kendrick Lamar", "Untitled 02") != \
        make_canonical_key("Kendrick Lamar", "Untitled 03")


def test_live_version_is_distinct_from_studio():
    assert make_canonical_key("Radiohead", "Idioteque") != \
        make_canonical_key("Radiohead", "Idioteque (Live)")


def test_same_title_different_artist_distinct():
    assert make_canonical_key("Drake", "Forever") != \
        make_canonical_key("Mac Miller", "Forever")


def test_key_shape_and_relationship_to_track_id():
    # 20-char sha1 prefix, same shape as make_track_id.
    assert len(make_canonical_key("Artist", "Track")) == 20
    # With no qualifier the two keys coincide (same algorithm, same input)...
    assert make_canonical_key("Artist", "Track") == make_track_id("Artist", "Track")
    # ...but a cosmetic suffix changes the track_id while the canonical_key holds.
    assert make_track_id("Artist", "Track (Explicit)") != make_track_id("Artist", "Track")
    assert make_canonical_key("Artist", "Track (Explicit)") == make_canonical_key("Artist", "Track")