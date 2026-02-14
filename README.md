# VacuumTest 🧹

**Audit your test suite for vacuum tests — tests that execute code but never verify anything.**

Coverage tells you "code was executed." VacuumTest tells you "code was verified."

## Detections

| Category | Example |
|---|---|
| `assertion-free` | Test with no `assert`, `pytest.raises`, or `mock.assert_*` |
| `tautological` | `assert True`, `assert x == x` |
| `overbroad-raises` | `pytest.raises(Exception)` — catches everything |
| `dead-assertion` | Assertions after `return` — never execute |
| `empty-parametrize` | `@parametrize("x", [])` — zero cases run |
| `type-only` | Only `isinstance()` checks, no value verification |

## Install

```bash
pip install -r requirements.txt
```

## CLI Usage

```bash
# Scan current directory
python vacuumtest.py

# Scan specific path
python vacuumtest.py tests/

# Output as SARIF for CI
python vacuumtest.py tests/ --format sarif > report.sarif

# Output as JSON
python vacuumtest.py tests/ --format json
```

The CLI exits with code **1** when issues are found, **0** when clean — plug it straight into your CI gate.

```bash
# Register plugin and enable audit
pytest -p pytest_vacuumtest --vacuum

# Or add to conftest.py / pyproject.toml so your team doesn't forget:
# [tool.pytest.ini_options]
# addopts = "-p pytest_vacuumtest --vacuum"
```
pytest -p pytest_vacuumtest --vacuum
```

Adds a **VacuumTest Assertion Audit** section to your terminal summary.

## Example Output

```
⚠️  VacuumTest: 3 issue(s)

  tests/test_api.py:12 [assertion-free] test_create_user → No assertions
  tests/test_api.py:28 [tautological] test_health → assert True always passes
  tests/test_db.py:45 [overbroad-raises] test_insert → pytest.raises(Exception) is too broad
```

## Run Tests

```bash
pytest test_vacuumtest.py -v
```

## License

MIT
