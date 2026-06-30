"""Unit tests for parsers.py — pure functions for HTML entities and athlete names.

Note: distance/duration parsing tests have moved to test_stat_parse.py
since those functions now live in kudosy.stat_parse.
"""

from kudosy.parsers import (
    decode_html_entities,
    parse_athlete_name,
)


class TestDecodeHtmlEntities:
    def test_amp(self) -> None:
        assert decode_html_entities("Tom &amp; Jerry") == "Tom & Jerry"

    def test_lt_gt(self) -> None:
        assert decode_html_entities("&lt;div&gt;") == "<div>"

    def test_quot(self) -> None:
        assert decode_html_entities("say &quot;hi&quot;") == 'say "hi"'

    def test_numeric_apos(self) -> None:
        assert decode_html_entities("it&#39;s") == "it's"

    def test_named_apos(self) -> None:
        assert decode_html_entities("it&apos;s") == "it's"

    def test_plain_text_unchanged(self) -> None:
        assert decode_html_entities("plain text") == "plain text"

    def test_empty_string(self) -> None:
        assert decode_html_entities("") == ""

    def test_unicode_passthrough(self) -> None:
        assert decode_html_entities("Köln &amp; Düsseldorf") == "Köln & Düsseldorf"


class TestParseAthleteName:
    """HTML snippets exercising both og:title attribute orders + title fallback."""

    def test_og_title_property_first(self) -> None:
        html = '<meta property="og:title" content="Jens van Almsick | Strava-Athletenprofil">'
        assert parse_athlete_name(html) == "Jens van Almsick"

    def test_og_title_content_first(self) -> None:
        html = '<meta content="Maria Müller | Strava" property="og:title">'
        assert parse_athlete_name(html) == "Maria Müller"

    def test_title_fallback(self) -> None:
        html = "<title>Klaus Schmidt | Strava</title>"
        assert parse_athlete_name(html) == "Klaus Schmidt"

    def test_html_entities_decoded(self) -> None:
        html = '<meta property="og:title" content="Tom &amp; Jerry | Strava">'
        assert parse_athlete_name(html) == "Tom & Jerry"

    def test_strava_only_rejected(self) -> None:
        html = '<meta property="og:title" content="Strava">'
        assert parse_athlete_name(html) is None

    def test_login_page_rejected(self) -> None:
        html = "<title>Log In | Strava</title>"
        assert parse_athlete_name(html) is None

    def test_no_name_in_html(self) -> None:
        html = "<html><body><p>Some page</p></body></html>"
        assert parse_athlete_name(html) is None

    def test_empty_html(self) -> None:
        assert parse_athlete_name("") is None

    def test_multi_separator_takes_first_part(self) -> None:
        html = '<meta property="og:title" content="Franz Müller | Cycling | Strava">'
        assert parse_athlete_name(html) == "Franz Müller"

    def test_og_title_preferred_over_title(self) -> None:
        html = (
            '<meta property="og:title" content="Anna | Strava"><title>BetterName | Strava</title>'
        )
        assert parse_athlete_name(html) == "Anna"
