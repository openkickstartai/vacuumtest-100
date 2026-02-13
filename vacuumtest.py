"""VacuumTest — Vacuum test & false coverage audit engine."""
import ast, sys, json
from pathlib import Path
from dataclasses import dataclass


@dataclass
class Issue:
    file: str
    line: int
    func: str
    cat: str
    msg: str


@dataclass
class TautologyFinding:
    """A single detected tautological assertion."""
    file: str
    lineno: int
    col_offset: int
    pattern_name: str
    source_snippet: str



class Analyzer(ast.NodeVisitor):
    def __init__(self, path):
        self.path, self.issues = str(path), []

    def analyze(self, src):
        self.visit(ast.parse(src))
        return self.issues

    def _add(self, line, func, cat, msg):
        self.issues.append(Issue(self.path, line, func, cat, msg))

    def visit_FunctionDef(self, node):
        if not node.name.startswith("test_"):
            return self.generic_visit(node)
        nm = node.name
        asserts = [n for n in ast.walk(node) if isinstance(n, ast.Assert)]
        calls = [n for n in ast.walk(node) if isinstance(n, ast.Call)
                 and isinstance(getattr(n, 'func', None), ast.Attribute)]
        has_verify = any(c.func.attr == "raises" or
                         c.func.attr.startswith("assert_") for c in calls)
        if not asserts and not has_verify:
            self._add(node.lineno, nm, "assertion-free",
                      "No assertions — expensive smoke test")
        for a in asserts:
            t = a.test
            if isinstance(t, ast.Constant) and t.value in (True, 1):
                self._add(a.lineno, nm, "tautological",
                          f"assert {t.value!r} always passes")
            if (isinstance(t, ast.Compare) and len(t.ops) == 1
                    and isinstance(t.ops[0], ast.Eq)
                    and ast.dump(t.left) == ast.dump(t.comparators[0])):
                self._add(a.lineno, nm, "tautological",
                          "Comparing value to itself")
        for c in calls:
            if (c.func.attr == "raises" and c.args
                    and isinstance(c.args[0], ast.Name)
                    and c.args[0].id in ("Exception", "BaseException")):
                self._add(c.lineno, nm, "overbroad-raises",
                          f"pytest.raises({c.args[0].id}) is too broad")
        for i, stmt in enumerate(node.body):
            if isinstance(stmt, ast.Return):
                for s in node.body[i + 1:]:
                    if any(isinstance(n, ast.Assert) for n in ast.walk(s)):
                        self._add(stmt.lineno, nm, "dead-assertion",
                                  "Assertion unreachable after return")
                break
        for d in node.decorator_list:
            if (isinstance(d, ast.Call)
                    and isinstance(d.func, ast.Attribute)
                    and d.func.attr == "parametrize" and len(d.args) >= 2
                    and isinstance(d.args[1], (ast.List, ast.Tuple))
                    and not d.args[1].elts):
                self._add(d.lineno, nm, "empty-parametrize",
                          "Empty parametrize — zero cases run")
        if asserts and all(
            isinstance(a.test, ast.Call) and isinstance(a.test.func, ast.Name)
            and a.test.func.id == "isinstance" for a in asserts
        ):
            self._add(node.lineno, nm, "type-only",
                      "Only type checks, no value verification")

    visit_AsyncFunctionDef = visit_FunctionDef


def scan_path(target):
    p = Path(target)
    if p.is_file():
        return Analyzer(p).analyze(p.read_text())
    issues = []
    for pat in ("test_*.py", "*_test.py"):
        for f in p.rglob(pat):
            issues.extend(Analyzer(f).analyze(f.read_text()))
    return issues


def format_text(issues):
    if not issues:
        return "✅ VacuumTest: All tests have meaningful assertions!"
    lines = [f"⚠️  VacuumTest: {len(issues)} issue(s)\n"]
    for i in issues:
        lines.append(f"  {i.file}:{i.line} [{i.cat}] {i.func} → {i.msg}")
    return "\n".join(lines)


def to_sarif(issues):
    return {
        "version": "2.1.0",
        "runs": [{"tool": {"driver": {"name": "VacuumTest"}},
                  "results": [{"ruleId": i.cat, "message": {"text": i.msg},
                               "locations": [{"physicalLocation": {
                                   "artifactLocation": {"uri": i.file},
                                   "region": {"startLine": i.line}}}]}
                              for i in issues]}]
    }


def main():
    import argparse
    ap = argparse.ArgumentParser(prog="vacuumtest",
                                 description="Audit test assertion quality")
    ap.add_argument("path", nargs="?", default=".")
    ap.add_argument("--format", choices=["text", "json", "sarif"], default="text")
    args = ap.parse_args()
    issues = scan_path(args.path)
    fmt = {"text": lambda: format_text(issues),
           "json": lambda: json.dumps([vars(i) for i in issues], indent=2),
           "sarif": lambda: json.dumps(to_sarif(issues), indent=2)}
    print(fmt[args.format]())
    sys.exit(1 if issues else 0)


if __name__ == "__main__":
    main()


class TautologicalAssertionDetector(ast.NodeVisitor):
    """AST-based detector for tautological (always-true) assertions.

    Identifies assertions that always pass and therefore verify nothing:

    * ``assert True`` / ``assert 1``  — literal truthy constants
    * ``assert x == x``              — self-comparison
    * ``assert isinstance(x, object)`` — always True for any value
    * ``assert len(x) >= 0``         — len() is always non-negative
    """

    def __init__(self, file: str = "<unknown>", source: str = "") -> None:
        """Initialise detector.

        Args:
            file: Path to the source file being analysed.
            source: Python source text (used for snippet extraction).
        """
        self.file: str = file
        self.source: str = source
        self.source_lines: list = source.splitlines() if source else []
        self.findings: list = []

    def detect(self, source: str) -> list:
        """Parse *source* and return all tautological-assertion findings.

        Args:
            source: Python source code to analyse.

        Returns:
            List of :class:`TautologyFinding` instances.
        """
        self.source = source
        self.source_lines = source.splitlines()
        self.findings = []
        tree = ast.parse(source)
        self.visit(tree)
        return self.findings

    # -- internal helpers ----------------------------------------------------

    def _snippet(self, node: ast.AST) -> str:
        """Return the trimmed source line for *node*."""
        idx = node.lineno - 1
        if 0 <= idx < len(self.source_lines):
            return self.source_lines[idx].strip()
        return ""

    def _add(self, node: ast.Assert, pattern_name: str) -> None:
        """Record a tautological finding."""
        self.findings.append(TautologyFinding(
            file=self.file,
            lineno=node.lineno,
            col_offset=node.col_offset,
            pattern_name=pattern_name,
            source_snippet=self._snippet(node),
        ))

    # -- visitor -------------------------------------------------------------

    def visit_Assert(self, node: ast.Assert) -> None:
        """Check every ``assert`` statement for known tautological patterns."""
        t = node.test
        self._check_assert_literal_true(node, t)
        self._check_self_compare(node, t)
        self._check_isinstance_object(node, t)
        self._check_len_gte_zero(node, t)
        self.generic_visit(node)

    # -- pattern checkers ----------------------------------------------------

    def _check_assert_literal_true(self, node: ast.Assert, t: ast.expr) -> None:
        """Detect ``assert True`` and ``assert 1``."""
        if not isinstance(t, ast.Constant):
            return
        if t.value is True:
            self._add(node, "assert_literal_true")
        elif isinstance(t.value, int) and not isinstance(t.value, bool) and t.value == 1:
            self._add(node, "assert_literal_true")

    def _check_self_compare(self, node: ast.Assert, t: ast.expr) -> None:
        """Detect ``assert x == x`` — comparing a value to itself."""
        if (isinstance(t, ast.Compare)
                and len(t.ops) == 1
                and isinstance(t.ops[0], ast.Eq)
                and len(t.comparators) == 1
                and ast.dump(t.left) == ast.dump(t.comparators[0])):
            self._add(node, "self_compare")

    def _check_isinstance_object(self, node: ast.Assert, t: ast.expr) -> None:
        """Detect ``assert isinstance(x, object)`` — always True."""
        if not isinstance(t, ast.Call):
            return
        func = t.func
        if (isinstance(func, ast.Name)
                and func.id == "isinstance"
                and len(t.args) == 2):
            second = t.args[1]
            if isinstance(second, ast.Name) and second.id == "object":
                self._add(node, "isinstance_object")

    def _check_len_gte_zero(self, node: ast.Assert, t: ast.expr) -> None:
        """Detect ``assert len(x) >= 0`` — len() always returns >= 0."""
        if not (isinstance(t, ast.Compare)
                and len(t.ops) == 1
                and len(t.comparators) == 1):
            return
        op = t.ops[0]
        left = t.left
        comp = t.comparators[0]
        # assert len(x) >= 0
        if (isinstance(op, ast.GtE)
                and self._is_len_call(left)
                and isinstance(comp, ast.Constant)
                and isinstance(comp.value, int)
                and not isinstance(comp.value, bool)
                and comp.value == 0):
            self._add(node, "len_gte_zero")
            return
        # assert 0 <= len(x)  (equivalent form)
        if (isinstance(op, ast.LtE)
                and isinstance(left, ast.Constant)
                and isinstance(left.value, int)
                and not isinstance(left.value, bool)
                and left.value == 0
                and self._is_len_call(comp)):
            self._add(node, "len_gte_zero")

    @staticmethod
    def _is_len_call(node: ast.expr) -> bool:
        """Return True if *node* is a call to the built-in ``len()``."""
        return (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "len")
