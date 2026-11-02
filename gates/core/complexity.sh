#!/bin/sh
set -eu
WORK=${FORGE_WORK:-/work}
python3 - "$WORK" <<'PY'
import ast
import sys
from pathlib import Path
root = Path(sys.argv[1]) / "projects"
limit = 15
class Complexity(ast.NodeVisitor):
    def __init__(self):
        self.value = 1
    def visit_If(self, node):
        self.value += 1
        self.generic_visit(node)
    def visit_For(self, node):
        self.value += 1
        self.generic_visit(node)
    def visit_While(self, node):
        self.value += 1
        self.generic_visit(node)
    def visit_ExceptHandler(self, node):
        self.value += 1
        self.generic_visit(node)
    def visit_BoolOp(self, node):
        self.value += max(0, len(node.values) - 1)
        self.generic_visit(node)
    def visit_comprehension(self, node):
        self.value += 1
        self.generic_visit(node)
if root.exists():
    for path in root.glob("*/src/**/*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                score = Complexity()
                score.visit(node)
                if score.value > limit:
                    print(str(path) + ":" + node.name + ":" + str(score.value), file=sys.stderr)
                    raise SystemExit(1)
PY
