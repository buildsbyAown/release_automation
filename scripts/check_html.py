#!/usr/bin/env python3
"""Check that HTML files have balanced, correctly nested tags."""
import sys
from html.parser import HTMLParser

VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _TagChecker(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.error = None

    def handle_starttag(self, tag, attrs):
        if tag not in VOID_TAGS:
            self.stack.append((tag, self.getpos()[0]))

    def handle_endtag(self, tag):
        if tag in VOID_TAGS or self.error:
            return
        if not self.stack or self.stack[-1][0] != tag:
            expected = f"</{self.stack[-1][0]}>" if self.stack else "no closing tag"
            self.error = f"unexpected </{tag}> on line {self.getpos()[0]} (expected {expected})"
        else:
            self.stack.pop()


def problem(text):
    """Return a description of the first problem, or None if the HTML is balanced."""
    checker = _TagChecker()
    checker.feed(text)
    checker.close()
    if checker.error:
        return checker.error
    if checker.stack:
        tag, line = checker.stack[-1]
        return f"<{tag}> opened on line {line} is never closed"
    return None


if __name__ == "__main__":
    failed = False
    for path in sys.argv[1:]:
        with open(path, encoding="utf-8") as f:
            issue = problem(f.read())
        if issue:
            print(f"::error file={path}::{issue}")
            failed = True
    sys.exit(1 if failed else 0)
