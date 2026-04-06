---
name: code-writing
category: capability
description: >
  Implementation methodology for writing clean, production-quality code. Covers pattern matching
  against existing codebases, interface-first design, SOLID principles enforcement, dependency
  injection, implementation ordering, and validation self-checks. Extracted from the coder and
  refactor agent definitions.
requires_tools:
  - read_file
  - write_file
  - replace
  - run_shell_command
  - grep_search
  - glob
  - list_directory
archetypes:
  - builder
primary_archetype: builder
compatible_with:
  - test-generation
  - security-analysis
  - api-design
  - debugging
conflicts_with:
  - code-review
requires:
  - solid-principles
enhances:
  - test-generation
  - architecture-design
temperature: 0.2
max_turns: 25
timeout_mins: 10
grounding_categories:
  - implementation
  - patterns
grounding_priority: high
derived_from:
  - coder
  - refactor
version: 1.0.0
---

# Code Writing

Write code that is maintainable, testable, and indistinguishable in style from the existing codebase. Every implementation begins with reading, not writing.

## Pattern Matching Protocol

Before writing any new code, read at least three existing files of the same type in the project. Extract the constructor pattern, dependency injection style, error handling approach, return type conventions, naming patterns, and file organization. New code must follow these patterns exactly so that a reviewer cannot distinguish new files from existing ones. When no existing examples of the file type exist, find the closest analog and adapt its patterns. In greenfield projects, follow the patterns specified in the design document or delegation prompt.

## Implementation Order

Always implement in this sequence: types and interfaces first to define contracts before any implementation; dependencies before dependents so that if module A imports module B, B is written first; inner layers before outer layers following domain to application to infrastructure to presentation; exports before consumers so the module exists before anything wires into it. Never write a consumer before the thing it consumes exists.

## Interface-First Workflow

For every new component, define the interface or type with full method signatures and documentation contracts. Identify all consumers and confirm the interface satisfies their needs. Implement the concrete class following the interface contract exactly. Register with the dependency injection container or export from the appropriate barrel file when the project uses those patterns. Never write a concrete implementation without its contract defined first.

## Refactoring Discipline

When modifying existing code, apply refactoring patterns systematically: extract method for single responsibility, introduce interface for dependency inversion, replace conditional with polymorphism, move method to proper owner, inline unnecessary abstractions, and replace magic values with named constants. Preserve all existing behavior during structural changes. One refactoring pattern per logical change. Verify behavior preservation at each step by confirming the same inputs produce the same outputs through equivalent code paths.

## Validation Self-Check

Before reporting completion, re-read every file created or modified to verify no syntax errors, missing imports, or incomplete implementations. Verify all imports resolve to files that exist. Verify all interface implementations fully satisfy their contracts with no missing methods or incorrect signatures. Run the validation command from the delegation prompt. If validation fails, diagnose and fix the issue, then re-validate. Never report a failing validation as success.

## Anti-Patterns

Do not write implementation code before defining its interface or type contract. Do not introduce a new pattern when the project already has an established one for the same concern. Do not create utility files or helper functions for single-use operations. Do not leave TODO comments or placeholder implementations in delivered code. Do not import from files outside the defined scope. Do not silently swallow errors instead of propagating them through the project's error handling pattern. Do not change behavior while refactoring.
