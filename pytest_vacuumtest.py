"""VacuumTest pytest plugin — adds --vacuum flag for assertion audit."""
from pathlib import Path
from vacuumtest import Analyzer


def pytest_addoption(parser):
    parser.addoption("--vacuum", action="store_true", default=False,
                     help="Enable VacuumTest assertion quality audit")


def pytest_collection_modifyitems(session, config, items):
    if not config.getoption("--vacuum", default=False):
        return
    seen, issues = set(), []
    for item in items:
        fspath = str(getattr(item, "path", item.fspath))
        if fspath not in seen:
            seen.add(fspath)
            try:
                src = Path(fspath).read_text("utf-8")
                issues.extend(Analyzer(fspath).analyze(src))
            except Exception:
                continue
    config._vacuum_issues = issues


def pytest_terminal_summary(terminalreporter, config):
    issues = getattr(config, "_vacuum_issues", None)
    if issues is None:
        return
    terminalreporter.section("VacuumTest Assertion Audit")
    if not issues:
        terminalreporter.write_line(
            "All tests have meaningful assertions!")
        return
    terminalreporter.write_line(
        f"{len(issues)} vacuum test issue(s) detected:\n")
    for i in issues:
        terminalreporter.write_line(
            f"  {i.file}:{i.line} [{i.cat}] {i.func}")
        terminalreporter.write_line(f"    -> {i.msg}")
