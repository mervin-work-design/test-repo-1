#!/usr/bin/env python3
"""Convert a markdown feature brief into a Jira-importable CSV of user stories.

Usage:
    python brief_to_jira.py brief.md -o stories.csv

Expected brief layout (flexible; see README.md for details):

    # Feature: Checkout Redesign          <- optional feature title (H1)

    Background text...                    <- ignored unless it is inside a story

    ## Story: Guest checkout              <- one story per heading
    Priority: High                        <- optional metadata lines
    Labels: checkout, mvp
    Story Points: 3

    As a guest shopper, I want to ...     <- description

    ### Acceptance Criteria               <- heading or "Acceptance Criteria:" line
    - Given ... when ... then ...
    - ...

Story detection: if any heading at the story level starts with "Story:" or
"User Story:", only those headings become stories (so "## Overview" or
"## Non-goals" sections are skipped). Otherwise every heading at the story
level is treated as a story.

Only the Python standard library is used.
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

JIRA_PRIORITIES = ("Highest", "High", "Medium", "Low", "Lowest")

# Accepted spellings -> Jira's default priority scheme.
PRIORITY_ALIASES = {
    "highest": "Highest", "critical": "Highest", "blocker": "Highest",
    "urgent": "Highest", "p0": "Highest",
    "high": "High", "major": "High", "p1": "High", "must": "High",
    "must have": "High", "must-have": "High",
    "medium": "Medium", "normal": "Medium", "moderate": "Medium",
    "p2": "Medium", "should": "Medium", "should have": "Medium",
    "should-have": "Medium",
    "low": "Low", "minor": "Low", "p3": "Low", "could": "Low",
    "could have": "Low", "could-have": "Low", "nice to have": "Low",
    "nice-to-have": "Low",
    "lowest": "Lowest", "trivial": "Lowest", "p4": "Lowest",
    "won't": "Lowest", "wont": "Lowest", "won't have": "Lowest",
}

# Metadata keys recognised at the top of a story body (case-insensitive).
META_KEYS = {
    "priority": "priority",
    "labels": "labels",
    "label": "labels",
    "tags": "labels",
    "story points": "story_points",
    "points": "story_points",
    "estimate": "story_points",
    "component": "components",
    "components": "components",
    "assignee": "assignee",
}

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
STORY_PREFIX_RE = re.compile(r"^(?:user\s+)?story\s*(?:\d+)?\s*[:\-–—.]\s*", re.I)
AC_TITLE_RE = re.compile(r"^\s*(?:\*\*|__)?\s*(acceptance\s+criteria|ac)\s*:?\s*(?:\*\*|__)?\s*:?\s*$", re.I)
META_RE = re.compile(r"^\s*(?:[-*+]\s+)?(?:\*\*|__)?([A-Za-z][A-Za-z ]*?)\s*:\s*(?:\*\*|__)?\s*:?\s*(.*?)\s*$")
LIST_ITEM_RE = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?(.*)$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")


@dataclass
class Story:
    title: str
    description_lines: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    priority: str = ""
    labels: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    story_points: str = ""
    assignee: str = ""

    @property
    def description(self) -> str:
        return _trim_blank_lines(self.description_lines)


@dataclass
class Brief:
    feature_title: str = ""
    stories: list[Story] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

def _trim_blank_lines(lines: list[str]) -> str:
    text = "\n".join(line.rstrip() for line in lines)
    # Collapse runs of 3+ newlines and strip outer whitespace.
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def normalize_priority(raw: str, default: str = "Medium") -> str:
    """Map free-form priority text onto Jira's default priority names."""
    if not raw:
        return default
    key = re.sub(r"[*_`]", "", raw).strip().lower()
    key = re.sub(r"\s+", " ", key)
    if key in PRIORITY_ALIASES:
        return PRIORITY_ALIASES[key]
    # Tolerate things like "High (launch blocker)" or "P1 - must ship".
    first = re.split(r"[\s(\-–—,/]+", key, maxsplit=1)[0]
    if first in PRIORITY_ALIASES:
        return PRIORITY_ALIASES[first]
    for name in JIRA_PRIORITIES:
        if key == name.lower():
            return name
    raise ValueError(f"Unrecognised priority: {raw!r}")


def _split_list(value: str) -> list[str]:
    return [v.strip() for v in re.split(r"[,;]", value) if v.strip()]


def _find_headings(lines: list[str]) -> list[tuple[int, int, str]]:
    """Return (line_index, level, text) for headings outside code fences."""
    headings = []
    in_fence = False
    for i, line in enumerate(lines):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = HEADING_RE.match(line)
        if m:
            headings.append((i, len(m.group(1)), m.group(2).strip()))
    return headings


def parse_brief(text: str, story_level: int | None = None) -> Brief:
    lines = text.splitlines()
    headings = _find_headings(lines)
    brief = Brief()

    h1 = [h for h in headings if h[1] == 1]
    if h1:
        brief.feature_title = re.sub(r"^(?:feature|epic)\s*[:\-–—]\s*", "", h1[0][2], flags=re.I)

    if story_level is None:
        # Shallowest heading level that contains a "Story:" heading, else H2,
        # else the shallowest level present below H1.
        prefixed = [h[1] for h in headings if STORY_PREFIX_RE.match(h[2])]
        if prefixed:
            story_level = min(prefixed)
        elif any(h[1] == 2 for h in headings):
            story_level = 2
        else:
            deeper = [h[1] for h in headings if h[1] > 1]
            story_level = min(deeper) if deeper else 2

    candidates = [h for h in headings if h[1] == story_level]
    explicit = [h for h in candidates if STORY_PREFIX_RE.match(h[2])]
    story_heads = explicit or candidates

    for idx, (line_no, level, title) in enumerate(story_heads):
        # A story ends at the next heading of the same or shallower level.
        end = len(lines)
        for h_line, h_level, _ in headings:
            if h_line > line_no and h_level <= level:
                end = h_line
                break
        title = STORY_PREFIX_RE.sub("", title).strip()
        brief.stories.append(_parse_story(title, lines[line_no + 1:end], level))

    return brief


def _parse_story(title: str, body: list[str], level: int) -> Story:
    story = Story(title=title)
    in_ac = False
    ac_heading_level = None
    in_fence = False
    in_meta_block = True  # metadata is only read before the description starts
    ac_item: list[str] | None = None

    def flush_ac_item():
        nonlocal ac_item
        if ac_item:
            story.acceptance_criteria.append(" ".join(ac_item).strip())
        ac_item = None

    for line in body:
        if FENCE_RE.match(line):
            in_fence = not in_fence
        if in_fence or FENCE_RE.match(line):
            flush_ac_item()
            if in_ac:
                story.acceptance_criteria.append(line.rstrip())
            else:
                story.description_lines.append(line)
            in_meta_block = False
            continue

        heading = HEADING_RE.match(line)
        if heading:
            h_level, h_text = len(heading.group(1)), heading.group(2).strip()
            if AC_TITLE_RE.match(h_text):
                flush_ac_item()
                in_ac, ac_heading_level = True, h_level
                in_meta_block = False
                continue
            if in_ac and ac_heading_level is not None and h_level <= ac_heading_level:
                flush_ac_item()
                in_ac = False
            # Keep other sub-headings as description text.
            if not in_ac:
                story.description_lines.append(line)
                in_meta_block = False
            continue

        if AC_TITLE_RE.match(line):
            flush_ac_item()
            in_ac, ac_heading_level = True, None
            in_meta_block = False
            continue

        if not line.strip():
            if in_ac:
                flush_ac_item()
            else:
                story.description_lines.append("")
            continue

        meta = META_RE.match(line)
        if meta and not in_ac:
            key = META_KEYS.get(meta.group(1).strip().lower())
            if key and (in_meta_block or key == "priority"):
                _apply_meta(story, key, meta.group(2))
                continue

        if in_ac:
            item = LIST_ITEM_RE.match(line)
            if item and (ac_item is None or len(item.group(1)) == 0 or not ac_item):
                flush_ac_item()
                ac_item = [item.group(2).strip()]
            elif item:
                # Nested list item: fold into parent criterion.
                ac_item.append(item.group(2).strip())
            elif ac_item is not None:
                ac_item.append(line.strip())  # continuation line
            else:
                ac_item = [line.strip()]  # plain paragraph criterion
            continue

        in_meta_block = False
        story.description_lines.append(line)

    flush_ac_item()
    return story


def _apply_meta(story: Story, key: str, value: str) -> None:
    value = value.strip().strip("*_").strip()
    if key == "priority":
        story.priority = value
    elif key == "labels":
        story.labels.extend(_split_list(value))
    elif key == "components":
        story.components.extend(_split_list(value))
    elif key == "story_points":
        story.story_points = value
    elif key == "assignee":
        story.assignee = value


# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #

def md_to_jira(text: str) -> str:
    """Lightweight markdown -> Jira wiki markup conversion."""
    out = []
    in_fence = False
    for line in text.splitlines():
        fence = FENCE_RE.match(line)
        if fence:
            if not in_fence:
                lang = line.strip()[3:].strip()
                out.append("{code:" + lang + "}" if lang else "{code}")
            else:
                out.append("{code}")
            in_fence = not in_fence
            continue
        if in_fence:
            out.append(line)
            continue

        heading = HEADING_RE.match(line)
        if heading:
            out.append(f"h{min(len(heading.group(1)), 6)}. {_inline_md_to_jira(heading.group(2))}")
            continue

        item = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?(.*)$", line)
        if item:
            depth = len(item.group(1).replace("\t", "  ")) // 2 + 1
            bullet = "#" if item.group(2)[0].isdigit() else "*"
            out.append(f"{bullet * depth} {_inline_md_to_jira(item.group(3))}")
            continue

        if line.lstrip().startswith(">"):
            out.append("bq. " + _inline_md_to_jira(line.lstrip()[1:].strip()))
            continue

        out.append(_inline_md_to_jira(line))
    return "\n".join(out)


def _inline_md_to_jira(text: str) -> str:
    # Protect inline code first.
    codes: list[str] = []

    def stash(m):
        codes.append(m.group(1))
        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", stash, text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"[\1|\2]", text)       # links
    text = re.sub(r"(\*\*|__)(.+?)\1", "\x01\\2\x01", text)            # bold
    text = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])", r"_\1_", text)  # *italic*
    text = re.sub(r"~~(.+?)~~", r"-\1-", text)                           # strike
    text = text.replace("\x01", "*")
    return re.sub(r"\x00(\d+)\x00", lambda m: "{{" + codes[int(m.group(1))] + "}}", text)


def _strip_inline_md(text: str) -> str:
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)
    return re.sub(r"(?<![*\w])[*_](?!\s)(.+?)(?<!\s)[*_](?![*\w])", r"\1", text)


def format_ac(items: list[str], markup: str) -> str:
    if markup == "jira":
        return "\n".join(
            line if line.startswith(("```", "~~~")) else f"* {_inline_md_to_jira(line)}"
            for line in items
        )
    return "\n".join(f"- {_strip_inline_md(i)}" for i in items)


def _label(value: str) -> str:
    # Jira labels cannot contain spaces.
    return re.sub(r"\s+", "-", value.strip())


# --------------------------------------------------------------------------- #
# CSV output
# --------------------------------------------------------------------------- #

def build_rows(
    brief: Brief,
    *,
    issue_type: str = "Story",
    default_priority: str = "Medium",
    markup: str = "jira",
    ac_in_description: bool = False,
    extra_labels: list[str] | None = None,
    feature_label: bool = False,
    parent: str = "",
    strict: bool = False,
) -> tuple[list[str], list[list[str]], list[str]]:
    """Return (header, rows, warnings)."""
    warnings: list[str] = []
    prepared = []
    for n, story in enumerate(brief.stories, 1):
        try:
            priority = normalize_priority(story.priority, default_priority)
        except ValueError as exc:
            if strict:
                raise
            warnings.append(f"Story {n} ({story.title!r}): {exc}; using {default_priority}")
            priority = default_priority

        if not story.acceptance_criteria:
            warnings.append(f"Story {n} ({story.title!r}): no acceptance criteria found")

        description = story.description
        if markup == "jira":
            description = md_to_jira(description)
        ac_text = format_ac(story.acceptance_criteria, markup)
        if ac_in_description and ac_text:
            heading = "h3. Acceptance Criteria" if markup == "jira" else "Acceptance Criteria:"
            description = f"{description}\n\n{heading}\n{ac_text}".strip()

        labels = list(story.labels) + list(extra_labels or [])
        if feature_label and brief.feature_title:
            labels.append(brief.feature_title)
        labels = list(dict.fromkeys(_label(l) for l in labels if l.strip()))

        prepared.append((story, priority, description, ac_text, labels))

    max_labels = max((len(p[4]) for p in prepared), default=0)
    max_components = max((len(p[0].components) for p in prepared), default=0)
    has_points = any(p[0].story_points for p in prepared)
    has_assignee = any(p[0].assignee for p in prepared)

    header = ["Summary", "Issue Type", "Priority", "Description", "Acceptance Criteria"]
    header += ["Labels"] * max_labels
    header += ["Component/s"] * max_components
    if has_points:
        header.append("Story Points")
    if has_assignee:
        header.append("Assignee")
    if parent:
        header.append("Parent")

    rows = []
    for story, priority, description, ac_text, labels in prepared:
        summary = _strip_inline_md(story.title)
        if len(summary) > 255:
            warnings.append(f"Summary truncated to 255 chars: {summary[:40]!r}...")
            summary = summary[:255]
        row = [summary, issue_type, priority, description, ac_text]
        row += labels + [""] * (max_labels - len(labels))
        row += story.components + [""] * (max_components - len(story.components))
        if has_points:
            row.append(story.story_points)
        if has_assignee:
            row.append(story.assignee)
        if parent:
            row.append(parent)
        rows.append(row)

    return header, rows, warnings


def write_csv(header: list[str], rows: list[list[str]], stream) -> None:
    writer = csv.writer(stream, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)


def convert(text: str, **kwargs) -> tuple[str, list[str]]:
    """Convenience wrapper: markdown text in, CSV text + warnings out."""
    story_level = kwargs.pop("story_level", None)
    brief = parse_brief(text, story_level=story_level)
    header, rows, warnings = build_rows(brief, **kwargs)
    buf = io.StringIO()
    write_csv(header, rows, buf)
    return buf.getvalue(), warnings


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Convert a markdown feature brief into a Jira CSV of user stories.",
    )
    p.add_argument("input", help="Markdown brief file, or '-' for stdin")
    p.add_argument("-o", "--output", default="-", help="CSV output file (default: stdout)")
    p.add_argument("--issue-type", default="Story", help="Jira issue type (default: Story)")
    p.add_argument("--default-priority", default="Medium", choices=JIRA_PRIORITIES,
                   help="Priority for stories without one (default: Medium)")
    p.add_argument("--story-level", type=int, choices=range(1, 7), metavar="N",
                   help="Heading level that marks a story (default: auto-detect)")
    p.add_argument("--markup", choices=("jira", "plain"), default="jira",
                   help="Text format for Description/AC cells (default: jira wiki markup)")
    p.add_argument("--ac-in-description", action="store_true",
                   help="Also append acceptance criteria to the Description field "
                        "(useful when your Jira has no Acceptance Criteria field)")
    p.add_argument("--label", action="append", default=[], dest="labels",
                   help="Extra label added to every story (repeatable)")
    p.add_argument("--feature-label", action="store_true",
                   help="Add the brief's H1 feature title as a label on every story")
    p.add_argument("--parent", default="", help="Parent/epic issue key, e.g. PROJ-123")
    p.add_argument("--strict", action="store_true",
                   help="Fail on unrecognised priorities instead of using the default")
    args = p.parse_args(argv)

    try:
        text = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        csv_text, warnings = convert(
            text,
            story_level=args.story_level,
            issue_type=args.issue_type,
            default_priority=args.default_priority,
            markup=args.markup,
            ac_in_description=args.ac_in_description,
            extra_labels=args.labels,
            feature_label=args.feature_label,
            parent=args.parent,
            strict=args.strict,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)

    if args.output == "-":
        sys.stdout.write(csv_text)
    else:
        Path(args.output).write_text(csv_text, encoding="utf-8", newline="")
    rows = list(csv.reader(io.StringIO(csv_text)))
    story_count = len(rows) - 1
    if story_count == 0:
        print("warning: no stories found in brief", file=sys.stderr)
    elif args.output != "-":
        print(f"Wrote {story_count} stories to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
