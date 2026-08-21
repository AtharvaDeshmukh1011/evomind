import inspect

from evomind.ingestion.git_miner import is_bug_fixing_commit, mine_repository


def test_detects_common_bug_fix_phrasing():
    assert is_bug_fixing_commit("Fix crash when parsing empty config")
    assert is_bug_fixing_commit("resolve NPE in dispatcher")
    assert is_bug_fixing_commit("BUG: off-by-one in pagination")


def test_ignores_non_bug_commits():
    assert not is_bug_fixing_commit("Add new dashboard widget")
    assert not is_bug_fixing_commit("Refactor auth module for clarity")
    assert not is_bug_fixing_commit("")


def test_default_extensions_are_not_python_only():
    # Regression test: mining used to hardcode (".py",), so a repo with no
    # Python files mined zero records and failed outright.
    default = inspect.signature(mine_repository).parameters["only_source_exts"].default
    assert ".py" in default
    assert ".js" in default
    assert len(default) > 1
