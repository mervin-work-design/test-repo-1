# brief_to_jira

Turns a markdown feature brief into a CSV of user stories you can bring in with
Jira's **External System Import → CSV**. It needs only Python 3.9+ and nothing
outside the standard library.

```bash
python brief_to_jira.py examples/checkout_brief.md -o stories.csv
```

## Writing the brief

```markdown
# Feature: Checkout Redesign        <- optional; used by --feature-label

## Overview                         <- skipped (no "Story:" prefix)

## Story: Guest checkout            <- one story per heading
Priority: High                      <- optional metadata, right under the heading
Labels: checkout, mvp
Story Points: 5
Component: Web

As a first-time shopper, I want ... <- becomes the Description

### Acceptance Criteria             <- or a plain "Acceptance Criteria:" line
- Given ... when ... then ...       <- each list item is one criterion
- ...
```

- **Finding stories:** headings that start with `Story:` or `User Story:` are
  stories. If no heading has that prefix, every heading at the story level
  (H2 by default) is a story. Use `--story-level N` to choose a different
  level.
- **Metadata:** you can add `Priority`, `Labels`/`Tags`, `Story Points`/`Points`,
  `Component(s)`, and `Assignee`. Bold keys such as `**Priority:** P1` also
  work.
- **Priority:** the script maps the value to Jira's default priority scheme
  (Highest, High, Medium, Low, Lowest). It understands:
  - `P0`–`P4`
  - `critical`, `blocker`, `major`, `minor`, `trivial`
  - MoSCoW terms (`must`, `should`, `could`, `won't`)

  A story with no priority gets `--default-priority` (Medium). A value the
  script doesn't recognise also gets the default and prints a warning. With
  `--strict`, it stops with an error instead.
- **Acceptance criteria:** each list item becomes one criterion, and the
  script removes checkboxes. Wrapped lines and nested sub-items are joined into
  their parent criterion.

## CSV output

| Column | Notes |
|---|---|
| Summary | Story title, with markdown removed and capped at 255 characters |
| Issue Type | `Story` (change it with `--issue-type`) |
| Priority | Normalized Jira priority |
| Description | Converted to Jira wiki markup (`--markup plain` keeps the text as written) |
| Acceptance Criteria | One `* item` per line |
| Labels (repeated) | One column per label, which is how Jira imports multiple values. Spaces become `-` |
| Component/s, Story Points, Assignee | Added only when at least one story has a value |
| Parent | Added only when you pass `--parent PROJ-123` (links stories to an epic) |

During the import, map **Acceptance Criteria** to your Acceptance Criteria
custom field. If your Jira doesn't have that field, pass `--ac-in-description`
to also add the criteria to the bottom of the Description.

### Other options

```
--label NAME          add a label to every story (repeatable)
--feature-label       add the H1 feature title as a label
-o -                  write to stdout (default)
```

## Tests

```bash
python -m unittest discover -s tests
```
