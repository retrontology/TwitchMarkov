import re
import pytest
from twitchmarkov.bot.filters import (
    compile_blacklist,
    is_blacklisted,
    meets_uniqueness,
    filter_message,
)


class TestCompileBlacklist:
    def test_valid_patterns_compiled(self):
        """Valid patterns should be compiled with word boundary and IGNORECASE."""
        patterns = compile_blacklist(["hello", "world"])
        assert len(patterns) == 2
        assert all(isinstance(p, re.Pattern) for p in patterns)

    def test_invalid_pattern_skipped_with_warning(self, caplog):
        """Invalid regex patterns should be skipped with a warning logged."""
        patterns = compile_blacklist(["(", "ok"])
        assert len(patterns) == 1
        assert "(" in caplog.text or "error" in caplog.text.lower()

    def test_word_boundary_matching(self):
        """Patterns should use word boundary \\b for matching."""
        patterns = compile_blacklist(["n[i1]gg"])
        # xNIGGx should NOT match (no word boundary)
        assert not is_blacklisted("xNIGGx", patterns)
        # NIGGx SHOULD match (word boundary at start)
        assert is_blacklisted("NIGGx", patterns)

    def test_case_insensitive(self):
        """Patterns should be case-insensitive."""
        patterns = compile_blacklist(["hello"])
        assert is_blacklisted("HELLO", patterns)
        assert is_blacklisted("Hello", patterns)
        assert is_blacklisted("hello", patterns)


class TestIsBlacklisted:
    def test_match_found(self):
        """Should return True when pattern matches."""
        patterns = compile_blacklist(["spam"])
        assert is_blacklisted("this is spam", patterns)

    def test_no_match(self):
        """Should return False when pattern doesn't match."""
        patterns = compile_blacklist(["spam"])
        assert not is_blacklisted("this is eggs", patterns)

    def test_empty_patterns(self):
        """Should return False with empty patterns."""
        assert not is_blacklisted("anything", [])


class TestMeetsUniqueness:
    def test_all_unique_words(self):
        """All unique words should meet any uniqueness threshold."""
        words = ["a", "b", "c", "d"]
        assert meets_uniqueness(words, 50)
        assert meets_uniqueness(words, 100)

    def test_half_unique(self):
        """50% unique should pass 50% threshold."""
        words = ["a", "b", "a", "b"]
        # 2 unique / 4 total = 50%
        assert meets_uniqueness(words, 50)
        assert not meets_uniqueness(words, 51)

    def test_low_uniqueness(self):
        """Low uniqueness should fail threshold."""
        words = ["a", "a", "a", "a"]
        # 1 unique / 4 total = 25%
        assert not meets_uniqueness(words, 50)

    def test_empty_words(self):
        """Empty word list should return False."""
        assert not meets_uniqueness([], 50)

    def test_single_word(self):
        """Single word is 100% unique."""
        assert meets_uniqueness(["a"], 100)
        assert meets_uniqueness(["a"], 50)


class TestFilterMessage:
    def test_demojize_emoji(self):
        """Emojis should be demojized to :emoji_name:."""
        result = filter_message("hi 😀", patterns=[], allow_mentions=True, percent_unique=1)
        assert result == "hi :grinning_face:"

    def test_blacklisted_returns_none(self):
        """Blacklisted messages should return None."""
        patterns = compile_blacklist(["spam"])
        result = filter_message("this is spam", patterns=patterns, allow_mentions=True, percent_unique=1)
        assert result is None

    def test_urls_stripped(self):
        """URLs should be stripped from message."""
        result = filter_message(
            "check this http://example.com out",
            patterns=[],
            allow_mentions=True,
            percent_unique=1
        )
        assert "http" not in result
        assert result == "check this out"

    def test_mentions_stripped_when_not_allowed(self):
        """@mentions should be stripped when allow_mentions=False."""
        result = filter_message(
            "hey @user how are you",
            patterns=[],
            allow_mentions=False,
            percent_unique=1
        )
        assert "@" not in result
        assert result == "hey how are you"

    def test_mentions_kept_when_allowed(self):
        """@mentions should be kept when allow_mentions=True."""
        result = filter_message(
            "hey @user how are you",
            patterns=[],
            allow_mentions=True,
            percent_unique=1
        )
        assert "@user" in result

    def test_uniqueness_check_fails(self):
        """Message with low uniqueness should return None."""
        # "a a a a" is 25% unique
        result = filter_message(
            "a a a a",
            patterns=[],
            allow_mentions=True,
            percent_unique=50
        )
        assert result is None

    def test_uniqueness_check_passes(self):
        """Message with high uniqueness should pass."""
        # "a b a b" is 50% unique (2 unique / 4 total)
        result = filter_message(
            "a b a b",
            patterns=[],
            allow_mentions=True,
            percent_unique=50
        )
        assert result is not None
        assert result == "a b a b"

    def test_whitespace_collapsed(self):
        """Multiple spaces should be collapsed to single space."""
        result = filter_message(
            "hello    world",
            patterns=[],
            allow_mentions=True,
            percent_unique=1
        )
        assert result == "hello world"

    def test_empty_after_cleaning_returns_none(self):
        """Empty message after cleaning should return None."""
        result = filter_message(
            "   ",
            patterns=[],
            allow_mentions=True,
            percent_unique=1
        )
        assert result is None

    def test_full_pipeline(self):
        """Test complete filter pipeline."""
        patterns = compile_blacklist(["spam"])
        result = filter_message(
            "hi  there 😀 check http://example.com spam",
            patterns=patterns,
            allow_mentions=True,
            percent_unique=1
        )
        # Should be blacklisted
        assert result is None

    def test_full_pipeline_clean(self):
        """Test complete filter pipeline with clean message."""
        patterns = compile_blacklist([])
        result = filter_message(
            "hi  there 😀 check http://example.com",
            patterns=patterns,
            allow_mentions=True,
            percent_unique=1
        )
        # emoji demojized, url stripped, whitespace collapsed
        assert result == "hi there :grinning_face: check"
