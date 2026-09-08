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
