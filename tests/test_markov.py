import random

import markovify
import pytest

from twitchmarkov.bot.markov import build_sentence, generate_sentence


ANIMALS = ["cat", "dog", "fox", "bird", "mouse", "goat", "frog", "duck"]
VERBS = ["sat", "ran", "jumped", "slept", "played", "hid", "walked", "sang"]
THINGS = ["mat", "roof", "porch", "chair", "tree", "fence", "step", "rug"]


def make_corpus() -> list[str]:
    corpus = []
    for animal in ANIMALS:
        for verb in VERBS:
            for thing in THINGS:
                corpus.append(f"the {animal} {verb} on the {thing}")
                if len(corpus) >= 40:
                    return corpus
    return corpus


class TestBuildSentenceEmptyCorpus:
    def test_empty_corpus_returns_none_without_calling_markovify(self, monkeypatch):
        def boom(*args, **kwargs):
            raise AssertionError("markovify.NewlineText should not be constructed for empty corpus")

        monkeypatch.setattr(markovify, "NewlineText", boom)

        result = build_sentence(
            [], state_size=1, times_to_try=10, unique=False, recent=[]
        )

        assert result is None


class TestBuildSentenceRealCorpus:
    def test_real_corpus_yields_sentence(self):
        random.seed(0)
        corpus = make_corpus()

        result = build_sentence(
            corpus,
            state_size=1,
            times_to_try=1000,
            unique=False,
            recent=[],
        )

        assert isinstance(result, str)
        assert result != ""


class TestBuildSentenceUniqueRecent:
    def test_unique_true_all_recent_returns_none_after_20_tries(self, monkeypatch):
        calls = []

        def fake_make_sentence(self, tries=10):
            calls.append(tries)
            return "the cat sat"

        monkeypatch.setattr(markovify.NewlineText, "make_sentence", fake_make_sentence)

        result = build_sentence(
            ["the cat sat"],
            state_size=1,
            times_to_try=10,
            unique=True,
            recent=["the cat sat"],
        )

        assert result is None
        assert len(calls) == 20

    def test_unique_true_not_in_recent_returns_sentence(self, monkeypatch):
        def fake_make_sentence(self, tries=10):
            return "the cat sat"

        monkeypatch.setattr(markovify.NewlineText, "make_sentence", fake_make_sentence)

        result = build_sentence(
            ["the cat sat"],
            state_size=1,
            times_to_try=10,
            unique=True,
            recent=["something else"],
        )

        assert result == "the cat sat"

    def test_unique_false_ignores_recent(self, monkeypatch):
        def fake_make_sentence(self, tries=10):
            return "the cat sat"

        monkeypatch.setattr(markovify.NewlineText, "make_sentence", fake_make_sentence)

        result = build_sentence(
            ["the cat sat"],
            state_size=1,
            times_to_try=10,
            unique=False,
            recent=["the cat sat"],
        )

        assert result == "the cat sat"


class TestBuildSentenceEmoji:
    def test_emoji_shortcode_is_emojized(self, monkeypatch):
        def fake_make_sentence(self, tries=10):
            return "hi :grinning_face:"

        monkeypatch.setattr(markovify.NewlineText, "make_sentence", fake_make_sentence)

        result = build_sentence(
            ["hi there"],
            state_size=1,
            times_to_try=10,
            unique=False,
            recent=[],
        )

        assert result == "hi 😀"


class TestBuildSentenceExceptionPath:
    def test_exception_from_markovify_returns_none_and_logs_warning(self, monkeypatch, caplog):
        def fake_make_sentence(self, tries=10):
            raise KeyError("boom")

        monkeypatch.setattr(markovify.NewlineText, "make_sentence", fake_make_sentence)

        with caplog.at_level("WARNING"):
            result = build_sentence(
                ["the cat sat"],
                state_size=1,
                times_to_try=10,
                unique=False,
                recent=[],
            )

        assert result is None
        assert any(record.levelname == "WARNING" for record in caplog.records)


class TestGenerateSentence:
    async def test_generate_sentence_matches_build_sentence(self, monkeypatch):
        def fake_make_sentence(self, tries=10):
            return "the cat sat"

        monkeypatch.setattr(markovify.NewlineText, "make_sentence", fake_make_sentence)

        result = await generate_sentence(
            ["the cat sat"],
            state_size=1,
            times_to_try=10,
            unique=False,
            recent=[],
        )

        assert result == "the cat sat"
