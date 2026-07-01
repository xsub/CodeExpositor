# ADR-005: Make AI explanations evidence-bound

Status: Accepted

## Context

LLMs can produce plausible but false explanations when given raw code or broad prompts.

## Decision

AI explanations must be generated only from extracted graph evidence, file locations, symbol metadata and confidence labels.

## Consequences

The system can expose uncertainty and avoid hallucinated architecture claims. Prompt design is constrained by graph query outputs.
