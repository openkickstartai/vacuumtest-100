"""VacuumTest — Vacuum test & false coverage audit engine."""
import ast, sys, json
from pathlib import Path
from dataclasses import dataclass, asdict


@dataclass
class Issue:
    file: str
    line: int
    func: str
    cat: str
    msg: str


SARIF_RULES = {
    "assertion-free": {
        "id": "assertion-free",
        "name": "AssertionFree",
        "shortDescription": {"text": "Test contains no assertions or verification calls"},
        "helpUri": "https://github.com/vacuumtest/vacuumtest#assertion-free",
    },
    "tautological": {
        "id": "tautological",
        "name": "TautologicalAssertion",
        "shortDescription": {"text": "Assertion always passes (e.g. assert True, assert x == x)"},
        "helpUri": "https://github.com/vacuumtest/vacuumtest#tautological",
    },
    "overbroad-raises": {
        "id": "overbroad-raises",
        "name": "OverbroadRaises",
        "shortDescription": {"text": "pytest.raises catches overly broad exception types"},
        "helpUri": "https://github.com/vacuumtest/vacuumtest#overbroad-raises",
    },
    "dead-assertion": {
        "id": "dead-assertion",
        "name": "DeadAssertion",
        "shortDescription": {"text": "Assertion after return statement — never executes"},
        "helpUri": "https://github.com/vacuumtest/vacuumtest#dead-assertion",
    },
    "empty-parametrize": {
        "id": "empty-parametrize",
        "name": "EmptyParametrize",
        "shortDescription": {"text": "Parametrize decorator with empty parameter list"},
        "helpUri": "https://github.com/vacuumtest/vacuumtest#empty-parametrize",
    },
    "type-only": {
        "id": "type-only",
        "name": "TypeOnlyAssertion",
        "shortDescription": {"text": "Only isinstance checks without value verification"},
        "helpUri": "https://github.com/vacuumtest/vacuumtest#type-only",
    },
}

SARIF_LEVEL = {
    "dead-assertion": "error",
    "empty-parametrize": "error",
}


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
                      "No assertions \u2014 expensive smoke test")
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
        # Dead assertion: assert after return
        for i, stmt in enumerate(node.body):
            if isinstance(stmt, ast.Return):
                for after in node.body[i + 1:]:
                    if isinstance(after, ast.Assert):
                        self._add(after.lineno, nm, "dead-assertion",
                                  "Assertion after return \u2014 never executes")
        # Empty parametrize
        for dec in node.decorator_list:
            if (isinstance(dec, ast.Call)
                    and isinstance(dec.func, ast.Attribute)
                    and dec.func.attr == "parametrize"
                    and len(dec.args) >= 2):
                arg2 = dec.args[1]
                if isinstance(arg2, (ast.List, ast.Tuple)) and len(arg2.elts) == 0:
                    self._add(dec.lineno, nm, "empty-parametrize",
                              "Empty parametrize \u2014 zero test cases")
        # Type-only: all asserts are isinstance checks
        if asserts and not has_verify:
            all_type = True
            for a in asserts:
                t = a.test
                if (isinstance(t, ast.Call) and isinstance(t.func, ast.Name)
                        and t.func.id == "isinstance"):
                    continue
                all_type = False
                break
            if all_type:
                self._add(node.lineno, nm, "type-only",
                          "Only isinstance checks \u2014 no value verification")
        self.generic_visit(node)


def format_text(issues):
    """Format issues as human-readable text."""
    if not issues:
        return "\u2705 No vacuum tests found."
    lines = [f"\u26a0\ufe0f  VacuumTest: {len(issues)} issue(s)\n"]
    for i in issues:
        lines.append(f"  {i.file}:{i.line} [{i.cat}] {i.func} \u2192 {i.msg}")
    return "\n".join(lines)


def to_sarif(issues):
    """Convert a list of Issue objects to a SARIF v2.1.0 dict."""
    used_ids = sorted(set(i.cat for i in issues))
    rules = [SARIF_RULES[rid] for rid in used_ids if rid in SARIF_RULES]

    results = []
    for issue in issues:
        results.append({
            "ruleId": issue.cat,
            "level": SARIF_LEVEL.get(issue.cat, "warning"),
            "message": {"text": issue.msg},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": issue.file},
                        "region": {
                            "startLine": issue.line,
                            "startColumn": 1,
                        },
                    }
                }
            ],
        })

    return {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/sarif-2.1/schema/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "VacuumTest",
                        "version": "1.0.0",
                        "informationUri": "https://github.com/vacuumtest/vacuumtest",
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="VacuumTest \u2014 audit test quality")
    parser.add_argument("paths", nargs="*", default=["."])
    parser.add_argument(
        "--format", choices=["text", "json", "sarif"],
        default="text", dest="fmt")
    parser.add_argument("--output", "-o", default=None,
                        help="Write output to file instead of stdout")
    args = parser.parse_args()

    issues = []
    for p in args.paths:
        root = Path(p)
        files = root.rglob("test_*.py") if root.is_dir() else [root]
        for f in files:
            try:
                src = f.read_text("utf-8")
                issues.extend(Analyzer(str(f)).analyze(src))
            except Exception:
                continue

    if args.fmt == "sarif":
        output = json.dumps(to_sarif(issues), indent=2)
    elif args.fmt == "json":
        output = json.dumps([asdict(i) for i in issues], indent=2)
    else:
        output = format_text(issues)

    if args.output:
        Path(args.output).write_text(output, "utf-8")
    else:
        print(output)

    sys.exit(1 if issues else 0)


if __name__ == "__main__":
    main()
