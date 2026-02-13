"""Tests for VacuumTest analyzer — verifies all 6 detection categories."""
from vacuumtest import Analyzer, format_text, to_sarif, Issue


def _issues(src, cat=None):
    result = Analyzer("test_sample.py").analyze(src)
    return [i for i in result if i.cat == cat] if cat else result


def test_detect_assertion_free():
    issues = _issues("def test_noop():\n    x = 1 + 1\n", "assertion-free")
    assert len(issues) == 1
    assert "No assertions" in issues[0].msg


def test_detect_assertion_free_with_print():
    issues = _issues("def test_p():\n    print('hi')\n", "assertion-free")
    assert len(issues) == 1


def test_detect_tautological_true():
    issues = _issues("def test_t():\n    assert True\n", "tautological")
    assert len(issues) == 1
    assert "True" in issues[0].msg


def test_detect_tautological_one():
    issues = _issues("def test_t():\n    assert 1\n", "tautological")
    assert len(issues) == 1


def test_detect_tautological_self_compare():
    src = "def test_t():\n    x = 5\n    assert x == x\n"
    issues = _issues(src, "tautological")
    assert len(issues) == 1
    assert "itself" in issues[0].msg


def test_detect_overbroad_raises():
    src = ("import pytest\ndef test_r():\n"
           "    with pytest.raises(Exception):\n        f()\n")
    issues = _issues(src, "overbroad-raises")
    assert len(issues) == 1
    assert "too broad" in issues[0].msg


def test_detect_overbroad_base_exception():
    src = ("import pytest\ndef test_r():\n"
           "    with pytest.raises(BaseException):\n        f()\n")
    issues = _issues(src, "overbroad-raises")
    assert len(issues) == 1


def test_detect_dead_assertion():
    src = "def test_d():\n    return\n    assert False\n"
    issues = _issues(src, "dead-assertion")
    assert len(issues) == 1
    assert "unreachable" in issues[0].msg.lower()


def test_detect_empty_parametrize():
    src = ("import pytest\n"
           "@pytest.mark.parametrize('x', [])\n"
           "def test_e(x):\n    assert x\n")
    issues = _issues(src, "empty-parametrize")
    assert len(issues) == 1


def test_detect_type_only():
    src = "def test_t():\n    assert isinstance([], list)\n"
    issues = _issues(src, "type-only")
    assert len(issues) == 1
    assert "type checks" in issues[0].msg.lower()


def test_clean_test_no_issues():
    src = "def test_good():\n    assert 2 + 2 == 4\n"
    assert len(_issues(src)) == 0


def test_non_test_function_ignored():
    src = "def helper():\n    x = 1\n"
    assert len(_issues(src)) == 0


def test_mock_assert_not_flagged():
    src = "def test_m():\n    mock.assert_called_once()\n"
    assert len(_issues(src, "assertion-free")) == 0


def test_pytest_raises_not_flagged_assertion_free():
    src = ("import pytest\ndef test_r():\n"
           "    with pytest.raises(ValueError):\n        f()\n")
    assert len(_issues(src, "assertion-free")) == 0
    assert len(_issues(src, "overbroad-raises")) == 0


def test_format_text_clean():
    assert "All tests have meaningful" in format_text([])


def test_format_text_with_issues():
    out = format_text([Issue("t.py", 1, "test_x", "tautological", "bad")])
    assert "1 issue" in out
    assert "tautological" in out


def test_sarif_structure():
    issues = [Issue("t.py", 5, "test_x", "dead-assertion", "unreachable")]
    sarif = to_sarif(issues)
    assert sarif["version"] == "2.1.0"
    assert len(sarif["runs"][0]["results"]) == 1
    assert sarif["runs"][0]["results"][0]["ruleId"] == "dead-assertion"
    assert sarif["runs"][0]["results"][0]["locations"][0][
        "physicalLocation"]["region"]["startLine"] == 5
