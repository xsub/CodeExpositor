# Code Expositor — AI Evidence Contract

AI is an explanation layer over extracted evidence. It is not the source of truth.

## Rules

1. AI receives only extracted evidence.
2. AI must cite graph nodes, files and symbol locations.
3. AI must distinguish confirmed edges from possible edges.
4. AI must say when a path is unresolved.
5. AI must not infer runtime behavior unless marked as runtime-observed.
6. AI must explain uncertainty.
7. AI must not invent modules, functions or relationships.

## Input Format

```json
{
  "question": "...",
  "graph_query": "...",
  "nodes": [],
  "edges": [],
  "evidence": [],
  "file_locations": [],
  "symbol_locations": [],
  "confidence": [],
  "limitations": []
}
```

`file_locations` and `symbol_locations` are derived only from selected graph nodes and evidence records. They are included so the LLM can cite files and symbols without scanning raw repository text.

The repository-level contract payload is available from the CLI:

```bash
expositor explain repository /path/to/repo --format payload
expositor explain module /path/to/repo --value libavcodec --format payload
expositor explain file /path/to/repo --value libavcodec/mpeg4videodec.c --format payload
expositor explain function /path/to/repo --value decode_frame --format payload
expositor explain path /path/to/repo --value decode_frame --format payload
expositor explain architecture /path/to/repo --value x86 --format payload
expositor explain where /path/to/repo --value decode_frame --format payload
```

## Output Format

```text
Answer
Evidence
Confidence
Uncertainty
Relevant files
Relevant functions
Suggested next query
```

## Explanation Types

- repository summary
- module summary
- file summary
- function summary
- path explanation
- architecture slice explanation
- “where is X implemented?” answer

## Hard Boundary

AI may produce prose only after deterministic graph queries have selected evidence. Raw repository dumps are not acceptable prompt input for final explanations.
