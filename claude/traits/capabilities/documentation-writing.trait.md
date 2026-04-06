---
name: documentation-writing
category: capability
description: >
  Technical documentation methodology covering audience detection, document structure selection,
  example quality verification, and staleness prevention. Writes for the reader using inverted
  pyramid structure with working code examples and scannable formatting. Extracted from the
  technical_writer agent definition.
requires_tools:
  - read_file
  - write_file
  - replace
  - grep_search
forbids_tools: []
archetypes:
  - builder
primary_archetype: builder
compatible_with:
  - api-design
  - code-writing
  - copywriting
conflicts_with: []
requires: []
enhances:
  - api-design
  - code-writing
temperature: 0.3
max_turns: 15
timeout_mins: 5
grounding_categories:
  - documentation
  - quality
grounding_priority: medium
derived_from:
  - technical_writer
version: 1.0.0
---

# Documentation Writing

Write clear, accurate developer documentation by reading the code first and writing for the target audience. Start with the most important information using inverted pyramid structure. Include working code examples for every API or feature. Keep language concise and direct with no filler, structuring documents for scannability with headers, lists, and tables.

## Audience Detection Protocol

Before writing anything, determine the target audience from the file type and context. README files target first-time users who have zero project context, optimized for clone-to-running in five minutes with prerequisites, installation, and a working example in the first screenful. API documentation targets integrating developers who have technical competence but zero project internals knowledge, optimized for finding the endpoint and its contract in thirty seconds with method, path, auth requirements, request/response schema, and a curl example per endpoint. Architecture documents target team members who have project context but limited historical context, optimized for understanding why decisions were made with decision rationale leading over description. Inline JSDoc targets contributing developers reading the function signature, optimized for understanding the function's contract without reading the body by documenting parameters, return value, thrown errors, and side effects.

## Document Structure Selection

Match structure to content type. Reference material for API endpoints, config options, and CLI flags uses alphabetical or grouped organization in table format where every entry has name, type, default value, description, and example value. Tutorials and guides for setup, migration, and deployment use sequential numbered steps where each step has exactly one action and one verification showing what to run and what the expected output is, including what to do when verification fails. Conceptual and architecture documents use top-down presentation with the big picture first then drilling into components, placing diagrams before prose and decision rationale before description.

## Example Quality Protocol

Every code example must be syntactically valid and runnable as-is so that copy-paste works. Use realistic values instead of foo, bar, and example.com. Show the most common use case first with edge cases and advanced usage second. Include expected output or response when the result is not obvious from the code. Declare prerequisites explicitly showing required imports, setup, and dependencies. Test all examples mentally for correctness before including them because an incorrect example is worse than no example.

## Staleness Prevention

Every documentation file must declare its source of truth by listing the code files, configurations, or APIs it documents. This enables verification that documentation matches the code it describes. When source files change, the documentation is flagged for review. Prefer linking to types and interfaces enforced by the compiler over duplicating their definitions to reduce maintenance burden and staleness risk.

## Anti-Patterns

Do not write documentation that describes what code does line-by-line instead of explaining why it exists and how to use it. Do not include setup instructions that assume a specific operating system without noting the assumption. Do not use screenshots for content that could be text or code blocks because screenshots rot faster and are not searchable. Do not document internal implementation details that consumers do not need to know. Do not write wall-of-text paragraphs instead of using structured formatting.
