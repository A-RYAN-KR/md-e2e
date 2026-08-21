# Living Documentation & Reports

md-e2e supports generating rich execution reports to share with both technical and non-technical stakeholders.

## Markdown summary Report
Generates a `summary.md` suitable for posting as GitHub PR comments, Notion docs, or Jira tickets.

It contains:
- Status badges indicating Suite Pass/Fail status.
- Checkbox progress lists:
  - `- [x]` for passed steps
  - `- [ ] ❌` for failed steps
  - `- [ ] ⚠️` for skipped steps
- Collapsible error callouts (`<details>`) containing inline failure screenshots and logs.
- Self-Healing diff sections showing exactly what elements were healed.

## Interactive HTML Dashboard
A standalone, zero-dependency HTML dashboard including:
- Interactive tab filters for Passed, Failed, and Healed scenarios.
- Scenario search filtering.
- Visual step timeline.
- Collapsible console error logs and system output.
- Embedded Playwright trace download link and online trace viewer link.
- HTML5 Video recording player for failure recordings.
