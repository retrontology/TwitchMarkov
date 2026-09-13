import logging
import re
from emoji import demojize


def compile_blacklist(patterns: list[str]) -> list[re.Pattern]:
    """Compile regex patterns with word boundary and case-insensitive matching.

    Skips patterns that fail to compile and logs a warning for each failure.
    """
    compiled = []
    logger = logging.getLogger(__name__)

    for pattern in patterns:
        try:
            compiled.append(re.compile(r"\b" + pattern, re.IGNORECASE))
        except re.error as e:
            logger.warning(f"Invalid regex pattern '{pattern}': {e}")

    return compiled


def is_blacklisted(text: str, patterns: list[re.Pattern]) -> bool:
    """Check if text matches any of the compiled blacklist patterns."""
    for pattern in patterns:
        if pattern.search(text):
            return True
    return False


def meets_uniqueness(words: list[str], percent_unique: float) -> bool:
    """Check if word uniqueness meets the threshold.

    Calculates: len(set(words)) / len(words) * 100 >= percent_unique
    Returns False for empty word lists.
    """
    if not words:
        return False

    unique_count = len(set(words))
    total_count = len(words)
    uniqueness_percent = (unique_count / total_count) * 100

    return uniqueness_percent >= percent_unique


def filter_message(
    text: str,
    *,
    patterns: list[re.Pattern],
    allow_mentions: bool,
    percent_unique: float,
) -> str | None:
    """Filter and clean a chat message.

    Pipeline (in order):
    1. Demojize emojis
    2. Check blacklist → return None if matched
    3. Strip URLs (http\\S+)
    4. Strip mentions (@\\S+) unless allow_mentions=True
    5. Check uniqueness → return None if below threshold
    6. Collapse whitespace and strip
    7. Return None if empty, otherwise return cleaned text
    """
    # Step 1: Demojize emojis
    text = demojize(text)

    # Step 2: Check blacklist
    if is_blacklisted(text, patterns):
        return None

    # Step 3: Strip URLs
    text = re.sub(r"http\S+", "", text)

    # Step 4: Strip mentions unless allow_mentions
    if not allow_mentions:
        text = re.sub(r"@\S+", "", text)

    # Step 5: Check uniqueness
    words = text.split()
    if not meets_uniqueness(words, percent_unique):
        return None

    # Step 6: Collapse whitespace and strip
    text = re.sub(r" +", " ", text).strip()

    # Step 7: Return None if empty
    if not text:
        return None

    return text
