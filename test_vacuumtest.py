"""Tests for VacuumTest analyzer — verifies all 6 detection categories and SARIF output."""
import json
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
    assert "return" in issues[0].msg


def test_detect_empty_parametrize():
    src = ("import pytest\n"
           "@pytest.mark.parametrize('x', [])\n"
           "def test_e(x):\n    assert x\n")
    issues = _issues(src, "empty-parametrize")
    assert len(issues) == 1


def test_detect_type_only():
    src = "def test_t():\n    assert isinstance(1, int)\n"
    issues = _issues(src, "type-only")
    assert len(issues) == 1


def test_no_false_positive_good_test():
    src = "def test_ok():\n    assert 1 + 1 == 2\n"
    issues = _issues(src)
    assert len(issues) == 0


def test_format_text_no_issues():
    out = format_text([])
    assert "No vacuum" in out


def test_format_text_with_issues():
    issues = [Issue("f.py", 1, "test_x", "assertion-free", "No assertions")]
    out = format_text(issues)
    assert "f.py" in out
    assert "assertion-free" in out


# ---------- SARIF output tests ----------

def test_sarif_required_fields():
    """SARIF output must contain $schema, version, and runs."""
    issues = [Issue("test_a.py", 10, "test_foo", "assertion-free",
                    "No assertions")]
    sarif = to_sarif(issues)
    assert "$schema" in sarif
    assert sarif["version"] == "2.1.0"
    assert "runs" in sarif
    assert isinstance(sarif["runs"], list)
    assert len(sarif["runs"]) == 1


def test_sarif_json_roundtrip():
    """SARIF output must be valid JSON that roundtrips correctly."""
    issues = [
        Issue("test_a.py", 10, "test_foo", "assertion-free", "No assertions"),
        Issue("test_b.py", 5, "test_bar", "tautological", "assert True always passes"),
    ]
    sarif = to_sarif(issues)
    text = json.dumps(sarif, indent=2)
    parsed = json.loads(text)
    assert parsed["$schema"] == sarif["$schema"]
    assert parsed["version"] == "2.1.0"
    assert len(parsed["runs"]) == 1
    assert len(parsed["runs"][0]["results"]) == 2


def test_sarif_tool_driver():
    """SARIF must include tool.driver with name and rules."""
    issues = [Issue("t.py", 1, "test_x", "overbroad-raises", "too broad")]
    sarif = to_sarif(issues)
    driver = sarif["runs"][0]["tool"]["driver"]
    assert driver["name"] == "VacuumTest"
    assert "rules" in driver
    assert len(driver["rules"]) >= 1
    rule = driver["rules"][0]
    assert "id" in rule
    assert "name" in rule
    assert "shortDescription" in rule
    assert "helpUri" in rule


def test_sarif_result_rule_id_mapping():
    """Each result ruleId must match issue category with correct locations."""
    issues = [
        Issue("test_a.py", 10, "test_foo", "assertion-free", "No assertions"),
        Issue("test_b.py", 20, "test_bar", "tautological", "assert True"),
        Issue("test_c.py", 30, "test_baz", "overbroad-raises", "too broad"),
    ]
    sarif = to_sarif(issues)
    results = sarif["runs"][0]["results"]
    assert len(results) == 3
    for i, result in enumerate(results):
        assert result["ruleId"] == issues[i].cat
        loc = result["locations"][0]["physicalLocation"]
        assert loc["artifactLocation"]["uri"] == issues[i].file
        assert loc["region"]["startLine"] == issues[i].line
        assert loc["region"]["startColumn"] == 1


def test_sarif_level_mapping():
    """dead-assertion and empty-parametrize map to error, others to warning."""
    issues = [
        Issue("t.py", 1, "test_a", "assertion-free", "msg"),
        Issue("t.py", 2, "test_b", "dead-assertion", "msg"),
        Issue("t.py", 3, "test_c", "empty-parametrize", "msg"),
        Issue("t.py", 4, "test_d", "tautological", "msg"),
    ]
    sarif = to_sarif(issues)
    results = sarif["runs"][0]["results"]
    assert results[0]["level"] == "warning"
    assert results[1]["level"] == "error"
    assert results[2]["level"] == "error"
    assert results[3]["level"] == "warning"


def test_sarif_rules_cover_three_categories():
    """SARIF rules list must cover at least 3 distinct detection categories."""
    issues = [
        Issue("t.py", 1, "test_a", "assertion-free", "msg"),
        Issue("t.py", 2, "test_b", "tautological", "msg"),
        Issue("t.py", 3, "test_c", "overbroad-raises", "msg"),
    ]
    sarif = to_sarif(issues)
    rules = sarif["runs"][0]["tool"]["driver"]["rules"]
    rule_ids = [r["id"] for r in rules]
    assert len(rule_ids) >= 3
    assert "assertion-free" in rule_ids
    assert "tautological" in rule_ids
    assert "overbroad-raises" in rule_ids


def test_sarif_empty_issues():
    """SARIF with no issues should still have valid structure."""
    sarif = to_sarif([])
    assert sarif["version"] == "2.1.0"
    assert "$schema" in sarif
    assert sarif["runs"][0]["results"] == []
    assert sarif["runs"][0]["tool"]["driver"]["rules"] == []


def test_sarif_result_message():
    """Each result must have a message with text field."""
    issues = [Issue("t.py", 5, "test_x", "tautological", "assert True always passes")]
    sarif = to_sarif(issues)
    result = sarif["runs"][0]["results"][0]
    assert "message" in result
    assert result["message"]["text"] == "assert True always passes"


def test_sarif_schema_url():
    """$schema must point to the SARIF v2.1.0 schema."""
    sarif = to_sarif([])
    assert "sarif" in sarif["$schema"].lower()
    assert "2.1.0" in sarif["$schema"]
