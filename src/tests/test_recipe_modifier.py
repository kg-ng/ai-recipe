"""
Tests for RecipeModifier.apply_edit, in particular the "silent no-op replace"
correctness bug: find_best_match only guarantees the CLOSEST line (fuzzy match),
not that `edit.find` is literally a substring of it. The original code did
`original_text.replace(edit.find, edit.replace)` unconditionally, which is a
no-op when `edit.find` isn't an exact substring - yet it still logged success
and a ChangeRecord claiming a change was made. This is exactly the kind of bug
that produces a diff UI showing "we changed X" when nothing actually changed.
"""

from llm_pipeline.models import ModificationEdit
from llm_pipeline.recipe_modifier import RecipeModifier


def test_replace_with_exact_substring_match_works_normally():
    rm = RecipeModifier()
    edit = ModificationEdit(
        target="ingredients", operation="replace",
        find="1 cup white sugar", replace="0.5 cup white sugar",
    )
    content = ["1 cup white sugar", "1 cup packed brown sugar"]
    modified, records = rm.apply_edit(edit, content)

    assert modified[0] == "0.5 cup white sugar"
    assert len(records) == 1
    assert records[0].from_text != records[0].to_text


def test_replace_falls_back_to_whole_line_when_find_not_exact_substring():
    """Regression test: LLM's `find` text ('1 cup sugar') doesn't exactly match
    the real ingredient line ('1 cup white sugar') due to paraphrasing. Fuzzy
    matching correctly identifies the line, but a literal substring replace
    would previously silently do nothing while still reporting success."""
    rm = RecipeModifier()
    edit = ModificationEdit(
        target="ingredients", operation="replace",
        find="1 cup sugar", replace="0.5 cup sugar",
    )
    content = ["1 cup white sugar", "1 cup packed brown sugar"]
    modified, records = rm.apply_edit(edit, content)

    assert modified[0] == "0.5 cup sugar", "must actually change the line, not silently no-op"
    assert len(records) == 1
    assert records[0].from_text == "1 cup white sugar"
    assert records[0].to_text == "0.5 cup sugar"
    assert records[0].from_text != records[0].to_text


def test_replace_that_would_produce_no_change_is_not_recorded():
    """If replace text is identical to the target, don't log a false-positive
    ChangeRecord claiming something changed."""
    rm = RecipeModifier()
    edit = ModificationEdit(
        target="ingredients", operation="replace",
        find="1 cup white sugar", replace="1 cup white sugar",
    )
    content = ["1 cup white sugar"]
    modified, records = rm.apply_edit(edit, content)

    assert modified == content
    assert records == []


# ---- matching: containment first, refuse ambiguity (found by src/evals, see evals/golden_modifier.json) ----

def test_phrase_quoted_from_a_long_line_is_found():
    """The prompt's own example uses find='about 10 minutes' inside a long instruction.
    Fuzzy similarity alone scores that far below the threshold, so the edit was silently dropped."""
    rm = RecipeModifier()
    edit = ModificationEdit(target="instructions", operation="replace", find="about 10 minutes", replace="about 8-9 minutes")
    content = ["Preheat the oven.", "Bake in the preheated oven until edges are nicely browned, about 10 minutes."]
    modified, records = rm.apply_edit(edit, content)

    assert modified[1] == "Bake in the preheated oven until edges are nicely browned, about 8-9 minutes."
    assert len(records) == 1


def test_find_that_fits_two_lines_is_refused_not_guessed():
    rm = RecipeModifier()
    edit = ModificationEdit(target="ingredients", operation="replace", find="shortening", replace="butter")
    content = ["0.5 cup shortening", "0.25 cup shortening"]
    modified, records = rm.apply_edit(edit, content)

    assert modified == content
    assert records == []


def test_exact_line_wins_over_a_similar_line():
    rm = RecipeModifier()
    edit = ModificationEdit(target="ingredients", operation="replace", find="0.25 cup shortening", replace="0.25 cup butter")
    modified, _ = rm.apply_edit(edit, ["0.5 cup shortening", "0.25 cup shortening"])

    assert modified == ["0.5 cup shortening", "0.25 cup butter"]


def test_fragment_find_with_a_full_line_replacement_does_not_nest_quantities():
    rm = RecipeModifier()
    edit = ModificationEdit(target="ingredients", operation="replace", find="packed brown sugar", replace="1.5 cups packed brown sugar")
    modified, _ = rm.apply_edit(edit, ["1 cup white sugar", "1 cup packed brown sugar"])

    assert modified == ["1 cup white sugar", "1.5 cups packed brown sugar"]


def test_fragment_find_with_a_fragment_replacement_still_edits_in_place():
    rm = RecipeModifier()
    edit = ModificationEdit(target="ingredients", operation="replace", find="white sugar", replace="brown sugar")
    modified, _ = rm.apply_edit(edit, ["1 cup white sugar", "2 eggs"])

    assert modified == ["1 cup brown sugar", "2 eggs"]
