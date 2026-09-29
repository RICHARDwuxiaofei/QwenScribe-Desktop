"""Advisory ASR comparison; manifest text remains authoritative."""
from __future__ import annotations

import re
from .gal_manifest import alignment_text, lexical


def distance(a: list[str], b: list[str]) -> int:
    row = list(range(len(b) + 1))
    for i, left in enumerate(a, 1):
        next_row = [i]
        for j, right in enumerate(b, 1):
            next_row.append(min(next_row[-1] + 1, row[j] + 1, row[j - 1] + (left != right)))
        row = next_row
    return row[-1]


def compare(expected: str, recognized: str, language: str) -> dict:
    clean = alignment_text(expected)
    if language == "en-US":
        tokens_expected = re.findall(r"[a-z0-9]+", clean.casefold())
        tokens_recognized = re.findall(r"[a-z0-9]+", recognized.casefold())
        metric = "WER"
    else:
        tokens_expected = list(lexical(clean))
        tokens_recognized = list(lexical(recognized))
        metric = "CER"
    edits = distance(tokens_expected, tokens_recognized)
    ratio = edits / max(1, len(tokens_expected))
    # A single same-length substitution in a short name is often an ASR
    # homophone. Keep it visible for review instead of declaring TTS wrong.
    short_name_typo = len(tokens_expected) == len(tokens_recognized) and edits == 1 and len(tokens_expected) <= 4
    status = "PASS" if ratio <= .03 else "REVIEW" if ratio <= .25 or short_name_typo else "FAIL"
    return {"expected": expected, "recognized": recognized, "normalized_expected": " ".join(tokens_expected) if language == "en-US" else "".join(tokens_expected), "normalized_recognized": " ".join(tokens_recognized) if language == "en-US" else "".join(tokens_recognized), "edit_distance": edits, "error_rate": ratio, "metric": metric, "status": status}
