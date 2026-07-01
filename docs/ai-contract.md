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
  "confidence": [],
  "limitations": []
}
```

## Output Format

```text
Answer
Evidence
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
