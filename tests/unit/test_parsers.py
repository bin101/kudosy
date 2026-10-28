"""Unit tests for parsers.py — pure functions for HTML entities and athlete names.

Note: distance/duration parsing tests have moved to test_stat_parse.py
since those functions now live in kudosy.stat_parse.
"""

import pytest

from kudosy.parsers import (
    decode_html_entities,
    is_strava_cookie_name,
    parse_athlete_name,
    parse_strava_cookies,
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

    def test_og_title_single_quotes_property_first(self) -> None:
        # A differing <title> proves the og:title pattern matched, not the fallback.
        html = (
            "<meta property='og:title' content='Anna Beispiel | Strava'>"
            "<title>Other Name | Strava</title>"
        )
        assert parse_athlete_name(html) == "Anna Beispiel"

    def test_og_title_single_quotes_content_first(self) -> None:
        html = (
            "<meta content='Anna Beispiel | Strava' property='og:title'>"
            "<title>Other Name | Strava</title>"
        )
        assert parse_athlete_name(html) == "Anna Beispiel"

    def test_og_title_single_quotes_may_contain_double_quote(self) -> None:
        html = "<meta property='og:title' content='Anna \"Ace\" Beispiel | Strava'>"
        assert parse_athlete_name(html) == 'Anna "Ace" Beispiel'

    def test_empty_og_title_content_does_not_run_into_next_tag(self) -> None:
        html = (
            '<meta property="og:title" content=""><meta name="x" content="Garbage | Strava">'
            "<title>Real Name | Strava</title>"
        )
        assert parse_athlete_name(html) == "Real Name"

    def test_empty_og_title_content_first_does_not_run_into_next_tag(self) -> None:
        html = '<meta content="" property="og:title"><meta name="x" content="Garbage | Strava">'
        assert parse_athlete_name(html) is None

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


class TestParseStravaCookies:
    def test_bare_value(self) -> None:
        assert parse_strava_cookies("abc123") == {"_strava4_session": "abc123"}

    def test_bare_value_with_equals_padding(self) -> None:
        assert parse_strava_cookies("abc123==") == {"_strava4_session": "abc123=="}

    def test_bare_value_with_quotes_and_whitespace(self) -> None:
        assert parse_strava_cookies('  "abc123"\n') == {"_strava4_session": "abc123"}

    def test_bare_value_with_clipboard_line_breaks(self) -> None:
        assert parse_strava_cookies("abc\n  def\r\nghi ") == {"_strava4_session": "abcdefghi"}

    def test_name_value_pairs(self) -> None:
        got = parse_strava_cookies("_strava4_session=s1; strava_remember_id=1; x_other=2")
        assert got == {"_strava4_session": "s1", "strava_remember_id": "1"}

    def test_full_cookie_header_with_prefix_and_tracking_dropped(self) -> None:
        header = (
            "Cookie: _ga=GA1.2.3; _strava4_session=s1; sp=zzz;\n"
            " strava_remember_id=42; strava_remember_token=tok"
        )
        assert parse_strava_cookies(header) == {
            "_strava4_session": "s1",
            "strava_remember_id": "42",
            "strava_remember_token": "tok",
        }

    def test_prefix_is_case_insensitive_and_quotes_stripped(self) -> None:
        assert parse_strava_cookies('"cookie: _strava4_session=s1"') == {"_strava4_session": "s1"}

    def test_prefixed_strava_cookies_are_kept(self) -> None:
        got = parse_strava_cookies("_strava4_session=s1; _strava_idcf=x; strava_foo=y")
        assert got == {"_strava4_session": "s1", "_strava_idcf": "x", "strava_foo": "y"}

    def test_remember_pair_without_session_is_valid(self) -> None:
        got = parse_strava_cookies("strava_remember_id=1; strava_remember_token=t")
        assert got == {"strava_remember_id": "1", "strava_remember_token": "t"}

    def test_remember_id_alone_is_invalid(self) -> None:
        with pytest.raises(ValueError):
            parse_strava_cookies("strava_remember_id=1; _ga=x")

    @pytest.mark.parametrize("text", ["", "   \n", "_ga=1; sp=2", "_strava4_session="])
    def test_invalid_inputs_raise(self, text: str) -> None:
        with pytest.raises(ValueError):
            parse_strava_cookies(text)


def test_is_strava_cookie_name() -> None:
    assert is_strava_cookie_name("_strava4_session")
    assert is_strava_cookie_name("strava_remember_token")
    assert not is_strava_cookie_name("_ga")
