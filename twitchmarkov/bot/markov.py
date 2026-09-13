import asyncio
import logging

import markovify
from emoji import emojize


def build_sentence(
    corpus: list[str],
    *,
    state_size: int,
    times_to_try: int,
    unique: bool,
    recent: list[str],
) -> str | None:
    """Build a markov-chain sentence from a corpus of text lines.

    Returns None for an empty corpus, if no sentence could be generated,
    or if markovify raises while building the model or generating text.
    """
    if not corpus:
        return None

    logger = logging.getLogger(__name__)

    try:
        text_model = markovify.NewlineText("\n".join(corpus), state_size=state_size)

        found = None
        if unique and recent:
            tries = 0
            while found is None and tries < 20:
                candidate = text_model.make_sentence(tries=times_to_try)
                if candidate is not None and candidate not in recent:
                    found = candidate
                tries += 1
        else:
            found = text_model.make_sentence(tries=times_to_try)
    except Exception as e:
        logger.warning(f"Failed to generate sentence: {e}")
        return None

    return emojize(found) if found else None


async def generate_sentence(
    corpus: list[str],
    *,
    state_size: int,
    times_to_try: int,
    unique: bool,
    recent: list[str],
) -> str | None:
    """Async wrapper around build_sentence, run in a worker thread."""
    return await asyncio.to_thread(
        build_sentence,
        corpus,
        state_size=state_size,
        times_to_try=times_to_try,
        unique=unique,
        recent=recent,
    )
