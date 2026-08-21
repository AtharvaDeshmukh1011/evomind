from evomind.ingestion.git_miner import is_bug_fixing_commit


def test_detects_common_bug_fix_phrasing():
    assert is_bug_fixing_commit("Fix crash when parsing empty config")
    assert is_bug_fixing_commit("resolve NPE in dispatcher")
    assert is_bug_fixing_commit("BUG: off-by-one in pagination")


def test_ignores_non_bug_commits():
    assert not is_bug_fixing_commit("Add new dashboard widget")
    assert not is_bug_fixing_commit("Refactor auth module for clarity")
    assert not is_bug_fixing_commit("")
