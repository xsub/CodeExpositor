# Tiny Example Outputs

These files are checked-in outputs generated from `corpus/tiny-c`.

Open the HTML report directly:

```text
examples/tiny/report.html
```

Generated files:

- `report.html` - static HTML report with embedded SVG diagrams.
- `mpeg4-case-study.json` - evidence-bound MPEG-4 case-study output.
- `calls.svg` - selected call graph SVG.
- `includes.dot` - Graphviz DOT include graph.

Regenerate them from the repository root:

```bash
python3 -m expositor.cli report corpus/tiny-c --html --output examples/tiny/report.html
python3 -m expositor.cli case-study mpeg4 corpus/tiny-c --format json --output examples/tiny/mpeg4-case-study.json
python3 -m expositor.cli export svg corpus/tiny-c --graph calls --renderer auto --output examples/tiny/calls.svg
python3 -m expositor.cli export dot corpus/tiny-c --graph includes --output examples/tiny/includes.dot
```
