"""VacuumTest pytest plugin — adds ``--vacuum`` flag for assertion audit.

This plugin integrates VacuumTest's static-analysis engine into the
pytest workflow.  When activated with ``--vacuum``, it analyses every
collected test file for vacuum-testing anti-patterns and prints a
dedicated report section in the terminal summary.

Usage::

    pytest -p pytest_vacuumtest --vacuum
"""
from pathlib import Path
from vacuumtest import Analyzer


def pytest_addoption(parser):
    """Register the ``--vacuum`` command-line option with pytest.

    This hook is called once during plugin initialisation to add the
    ``--vacuum`` boolean flag.  When the flag is present on the command
    line, VacuumTest analysis is enabled during the collection phase.

    Trigger timing:
        Called during pytest startup, before any test collection begins.

    Args:
        parser: The pytest argument parser instance used to register
            new command-line options.
    """
    parser.addoption("--vacuum", action="store_true", default=False,
                     help="Enable VacuumTest assertion quality audit")


def pytest_collection_modifyitems(session, config, items):
    """Analyse collected test files for vacuum-test anti-patterns.

    After pytest has collected all test items this hook reads each
    unique test file, runs the VacuumTest analyser on its source, and
    stores the discovered issues on ``config._vacuum_issues`` for later
    reporting by :func:`pytest_terminal_summary`.

    Trigger timing:
        Called after all test items have been collected (and any
        deselection has been applied), but before test execution starts.

    Args:
        session: The current pytest ``Session`` object.
        config: The pytest ``Config`` object.  Used to check the
            ``--vacuum`` flag and to store results as
            ``config._vacuum_issues``.
        items: List of collected ``Item`` objects.  Each item's
            ``path`` (or legacy ``fspath``) attribute is used to
            locate the corresponding source file on disk.

    Note:
        Files that cannot be read or parsed are silently skipped so
        that a single unparseable file does not block the entire
        audit.  Each file is analysed at most once regardless of how
        many test items it contains.
    """
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
    """Display VacuumTest analysis results in the terminal summary.

    Appends a *VacuumTest Assertion Audit* section to the pytest
    terminal output after all tests have completed.  If no issues were
    found a reassuring message is printed; otherwise every issue is
    listed with its file, line, category, and description.

    Trigger timing:
        Called after all tests have finished and the standard pytest
        summary (pass / fail counts) has been printed, but before the
        final exit-code is determined.

    Args:
        terminalreporter: The ``TerminalReporter`` instance used to
            write section headers and individual output lines.
        config: The pytest ``Config`` object.  Checked for the
            ``_vacuum_issues`` list that was populated during
            collection by :func:`pytest_collection_modifyitems`.
    """
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
