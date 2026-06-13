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
    "Untitled 02",
    "Untitled 03",
    "Pt. 1",
    "Pt. 2",
    "Act II",
    "Song (Tiesto Remix)",        # named remixer — distinct, not normalized
    "Song (Live at Wembley)",     # specific recording — distinct, not normalized
])
def test_keeps_distinct_songs_untouched(raw):
    # Different songs / specific recordings must pass through untouched.
    assert canonical_title(raw) == raw.strip()


@pytest.mark.parametrize("raw, expected", [
    ("Song (Live)", "Song (live)"),
    ("Song - live", "Song (live)"),
    ("Song (Live Version)", "Song (live)"),
    ("Song [Live]", "Song (live)"),
    ("Song (Acoustic)", "Song (acoustic)"),
    ("Song (Acoustic Version)", "Song (acoustic)"),
    ("Song (Remix)", "Song (remix)"),
    ("Song (Demo)", "Song (demo)"),
    ("Song (Instrumental)", "Song (instrumental)"),
])
def test_normalizes_variant_markers(raw, expected):
    # Variant markers are kept (distinct from studio) but normalized to one form.
    assert canonical_title(raw) == expected


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


def test_variant_spellings_merge():
    # The reported case: three spellings of one live recording fold together,
    # but stay distinct from the studio cut.
    live = make_canonical_key("America", "Tin Man (Live)")
    assert make_canonical_key("America", "Tin man - live") == live
    assert make_canonical_key("America", "Tin Man (Live Version)") == live
    assert make_canonical_key("America", "Tin Man [Live]") == live
    assert make_canonical_key("America", "Tin Man") != live


def test_bare_remix_merges_but_named_remixes_stay_distinct():
    assert make_canonical_key("X", "Song (Remix)") == make_canonical_key("X", "Song - Remix")
    # A remixer name differentiates genuinely different remixes — keep them apart.
    assert make_canonical_key("X", "Song (Tiesto Remix)") != \
        make_canonical_key("X", "Song (Skrillex Remix)")


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