# Code Expositor — Canonical Graph Model

The project owns its graph model. External tools feed this model through adapters. No external tool may define the internal schema.

## Executable Schema

The canonical schema is available directly from Expositor Core:

```bash
expositor schema
```

This emits the graph index version, node types, edge types, confidence labels, dataclass fields and the evidence contract used by adapters, storage, validation, query clients and reports.

## Node Types

- Repository
- Directory
- File
- SourceFile
- HeaderFile
- TranslationUnit
- Module
- Library
- Namespace
- Class
- Struct
- Enum
- Macro
- Function
- Method
- Variable
- Typedef
- Symbol
- CallSite
- BuildTarget
- Architecture
- CompilerFlag
- FeatureFlag
- PublicAPI
- EntryPoint

## Edge Types

- CONTAINS
- DECLARES
- DEFINES
- REFERENCES
- INCLUDES
- DEPENDS_ON
- CALLS
- MAY_CALL
- UNRESOLVED
- ASSIGNS_FUNCTION_POINTER
- USES_CALLBACK
- REGISTERED_AS
- COMPILED_IN
- EXCLUDED_BY
- ARCH_SPECIFIC
- EXPORTED_BY
- ENTRY_REACHES
- HAS_EVIDENCE

## Edge Metadata

Every edge must support:

- source node
- target node
- confidence
- extraction tool
- evidence location
- build context
- architecture context
- index version

## Confidence Levels

- CONFIRMED
- LIKELY
- POSSIBLE
- UNRESOLVED
- OBSERVED_RUNTIME

## Query API v0.1

- repo_summary()
- module_summary(path)
- file_summary(path)
- symbols_in(path)
- public_api(module)
- includes_of(file)
- dependents_of(path)
- callers_of(function)
- callees_of(function)
- paths_to(function, max_depth)
- paths_from(entrypoint, target, max_depth)
- architecture_slice(arch)
- why_reachable(function)
- evidence_for(node_or_edge)

Queries return structured data. AI receives query results and evidence, then generates explanations.
