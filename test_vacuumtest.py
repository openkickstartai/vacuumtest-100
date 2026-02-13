"""Tests for VacuumTest analyzer — verifies all 6 detection categories."""
from vacuumtest import Analyzer, format_text, to_sarif, Issue
from vacuumtest import TautologicalAssertionDetector, TautologyFinding



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


# ---------------------------------------------------------------------------
# Helpers for TautologicalAssertionDetector tests
# ---------------------------------------------------------------------------

def _detect(src: str) -> list:
    """Run detector on source and return all findings."""
    detector = TautologicalAssertionDetector("test_sample.py", src)
    return detector.detect(src)


def _detect_pattern(src: str, pattern: str) -> list:
    """Run detector and filter findings by pattern_name."""
    return [f for f in _detect(src) if f.pattern_name == pattern]


# ---------------------------------------------------------------------------
# Pattern 1: assert_literal_true  (assert True / assert 1)
# ---------------------------------------------------------------------------

def test_tautological_assert_true_positive_bool():
    """assert True is always tautological."""
    findings = _detect_pattern("assert True\n", "assert_literal_true")
    assert len(findings) == 1
    assert findings[0].pattern_name == "assert_literal_true"
    assert findings[0].lineno == 1


def test_tautological_assert_true_positive_int_one():
    """assert 1 is tautological (truthy constant)."""
    findings = _detect_pattern("assert 1\n", "assert_literal_true")
    assert len(findings) == 1


def test_tautological_assert_true_negative_false():
    """assert False is NOT tautological (it always fails)."""
    findings = _detect_pattern("assert False\n", "assert_literal_true")
    assert len(findings) == 0


def test_tautological_assert_true_negative_variable():
    """assert x (a variable) is NOT tautological — value unknown."""
    findings = _detect_pattern("x = True\nassert x\n", "assert_literal_true")
    assert len(findings) == 0


# ---------------------------------------------------------------------------
# Pattern 2: self_compare  (assert x == x)
# ---------------------------------------------------------------------------

def test_tautological_self_compare_positive_simple():
    """assert x == x is a self-comparison tautology."""
    findings = _detect_pattern("x = 5\nassert x == x\n", "self_compare")
    assert len(findings) == 1


def test_tautological_self_compare_positive_longer_name():
    """Longer variable names should still be detected."""
    findings = _detect_pattern("result = get()\nassert result == result\n", "self_compare")
    assert len(findings) == 1


def test_tautological_self_compare_negative_different_vars():
    """assert x == y with different names must NOT be flagged."""
    findings = _detect_pattern("assert x == y\n", "self_compare")
    assert len(findings) == 0


def test_tautological_self_compare_negative_noteq_operator():
    """assert x != x uses NotEq, not Eq — not our pattern."""
    findings = _detect_pattern("assert x != x\n", "self_compare")
    assert len(findings) == 0


# ---------------------------------------------------------------------------
# Pattern 3: isinstance_object  (assert isinstance(x, object))
# ---------------------------------------------------------------------------

def test_tautological_isinstance_object_positive_simple():
    """isinstance(x, object) is always True."""
    findings = _detect_pattern("assert isinstance(x, object)\n", "isinstance_object")
    assert len(findings) == 1
    assert findings[0].pattern_name == "isinstance_object"


def test_tautological_isinstance_object_positive_other_var():
    """Works with any first argument."""
    findings = _detect_pattern("assert isinstance(my_var, object)\n", "isinstance_object")
    assert len(findings) == 1


def test_tautological_isinstance_object_negative_int():
    """isinstance(x, int) is a real check — not tautological."""
    findings = _detect_pattern("assert isinstance(x, int)\n", "isinstance_object")
    assert len(findings) == 0


def test_tautological_isinstance_object_negative_str():
    """isinstance(x, str) is a real check — not tautological."""
    findings = _detect_pattern("assert isinstance(x, str)\n", "isinstance_object")
    assert len(findings) == 0


# ---------------------------------------------------------------------------
# Pattern 4: len_gte_zero  (assert len(x) >= 0)
# ---------------------------------------------------------------------------

def test_tautological_len_gte_zero_positive_simple():
    """len(x) >= 0 is always true."""
    findings = _detect_pattern("assert len(x) >= 0\n", "len_gte_zero")
    assert len(findings) == 1


def test_tautological_len_gte_zero_positive_named_list():
    """Same pattern with a different variable name."""
    findings = _detect_pattern("assert len(items) >= 0\n", "len_gte_zero")
    assert len(findings) == 1


def test_tautological_len_gte_zero_negative_gte_one():
    """len(x) >= 1 is a meaningful check."""
    findings = _detect_pattern("assert len(x) >= 1\n", "len_gte_zero")
    assert len(findings) == 0


def test_tautological_len_gte_zero_negative_gt_zero():
    """len(x) > 0 is meaningful (fails for empty)."""
    findings = _detect_pattern("assert len(x) > 0\n", "len_gte_zero")
    assert len(findings) == 0


# ---------------------------------------------------------------------------
# Cross-cutting: dataclass fields & no false positives on real assertions
# ---------------------------------------------------------------------------

def test_tautological_finding_fields():
    """TautologyFinding carries file, lineno, col_offset, pattern, snippet."""
    findings = _detect("assert True\n")
    assert len(findings) == 1
    f = findings[0]
    assert f.file == "test_sample.py"
    assert f.lineno == 1
    assert f.col_offset == 0
    assert f.source_snippet == "assert True"


def test_tautological_no_false_positive_real_assertion():
    """A real assertion must produce zero findings."""
    src = "assert result == 42\nassert isinstance(x, int)\nassert len(x) >= 1\n"
    findings = _detect(src)
    assert len(findings) == 0
