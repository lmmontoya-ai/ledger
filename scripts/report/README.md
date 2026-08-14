# Editing the report

The prose lives in **`report.md`**. Edit that file, run one command, done:

```
.venv\Scripts\python.exe -X utf8 scripts\report\assemble.py          # full
.venv\Scripts\python.exe -X utf8 scripts\report\assemble.py --quick  # skip
```

`--quick` skips re-reading the engine and the run artifacts (fast, use it
while writing); the full build re-harvests every number. Output:
`docs/report/ledger_story.html`, self-contained, ready to publish.

## The syntax

Ordinary markdown paragraphs, blank line between them, plus:

| You write | You get |
|---|---|
| `# Title {#id}` | a new section, with `id` used by the contents bar |
| `## Title` | a subheading |
| `!! Head line` then body lines | a shaded finding box |
| `?? Head line` then body lines | a bordered note box |
| `@figure some-id` | an empty div a chart script fills |
| `@chart some-id` + caption lines | a chart with a caption underneath |
| `@html <anything>` | raw HTML, one line, escape hatch |
| `\| a \| b \|` table rows | a table (first row is the header) |
| `**bold**` `*italic*` `` `code` `` `[text](url)` | as expected |
| `{{some-anchor}}` | **a number injected from the data** |

## The one rule that matters

**Never type a result into the prose.** Write `{{v2-hself}}` and the build
fills it from the run artifacts. If a number has no anchor yet, add it in
two places: `harvest.py` (read it from the artifact) and `report.js`
(`setText("your-anchor", ...)`). The build refuses to produce a report
whose prose has lost an anchor the data expects, which is what stops a
figure and a sentence from disagreeing.

Also: no em dashes. The build fails on them.

## Files

| File | What it is |
|---|---|
| `report.md` | **the prose. Edit this.** |
| `report.js` | charts and the injected numbers |
| `harvest.py` | reads the engine and the run artifacts into `report_data.json` |
| `assemble.py` | renders markdown, embeds data, checks consistency, writes the HTML |
| `md_render.py` | the markdown renderer |
| `report_body.html` | build artifact, rewritten on every build. Do not edit |
| `html_to_md.py` | one-time migration that produced `report.md` |
