"""
A deliberately simple, no-LLM baseline: cue words in each sentence decide the modification type.

It exists to give the eval a floor to beat and to prove the metrics can tell a weak extractor
from a strong one. It is NOT the pipeline's extractor.
"""

import re
from typing import Callable, List, Tuple

from llm_pipeline.models import ModificationEdit, ModificationObject

# (modification_type, cue regex), checked in order; a sentence can yield several types.
_CUES: List[Tuple[str, "re.Pattern[str]"]] = [
    ("removal", re.compile(r"\b(omit(ted)?|left out|leave out|without)\b")),
    ("ingredient_substitution", re.compile(r"\b(instead of|substitut\w*|swap\w*)\b")),
    ("addition", re.compile(r"\b(add(ed|ing)?|threw in|throw in|drizzled|extra)\b")),
    ("quantity_adjustment", re.compile(r"\b(less|more|half|double|at least|lots of|1/2|\d+\s?(tsp|cup|c\b|lb))")),
    ("technique_change", re.compile(r"\b(refrigerat\w*|chill\w*|pressed|press them|scoop\w*|bake[d]? (longer|shorter))\b")),
]
_SPLIT = re.compile(r"(?<=[.!?])\s+|[;\n]|\(\d\)")


def keyword_baseline(review_text: str) -> List[ModificationObject]:
    mods: List[ModificationObject] = []
    for sentence in (s.strip() for s in _SPLIT.split(review_text)):
        if not sentence:
            continue
        lowered = sentence.lower()
        for mod_type, cue in _CUES:
            if cue.search(lowered):
                mods.append(
                    ModificationObject(
                        modification_type=mod_type,
                        reasoning=sentence,
                        edits=[ModificationEdit(target="ingredients", operation="replace", find=sentence, replace=sentence)],
                    )
                )
    return mods


def oracle_from_gold(gold_tweaks: list) -> List[ModificationObject]:
    """Perfect predictions built from the labels. Used to check that the metrics reward a perfect answer."""
    return [
        ModificationObject(
            modification_type=g["modification_type"],
            reasoning=g["must_mention"][0],
            edits=[ModificationEdit(target="ingredients", operation="replace", find=g["must_mention"][0], replace="x")],
        )
        for g in gold_tweaks
        if g.get("scored", True)
    ]
