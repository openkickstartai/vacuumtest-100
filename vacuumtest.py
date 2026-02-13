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
