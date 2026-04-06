---
name: refactoring
category: capability
description: >
  Structural improvement methodology covering behavior preservation verification, safe refactoring
  sequencing, code smell identification and resolution, and scope boundary enforcement. Changes
  structure without changing behavior through incremental, verified transformations. Extracted from
  the refactor agent definition.
requires_tools:
  - read_file
  - write_file
  - replace
  - run_shell_command
  - grep_search
forbids_tools: []
archetypes:
  - builder
primary_archetype: builder
compatible_with:
  - code-writing
  - test-generation
conflicts_with:
  - code-review
requires: []
enhances:
  - code-writing
  - test-generation
temperature: 0.2
max_turns: 25
timeout_mins: 10
grounding_categories:
  - implementation
  - quality
grounding_priority: medium
derived_from:
  - refactor
version: 1.0.0
---

# Refactoring

Improve code structure while preserving existing behavior through incremental, safe transformations. Read and understand existing behavior before making any changes. Every structural change must be verified to produce the same outputs for the same inputs.

## Behavior Preservation Verification

At every refactoring step, identify the observable behavior before the change including inputs, outputs, side effects, and error handling. Apply the structural change. Verify the same inputs produce the same outputs through equivalent code paths. If behavior preservation cannot be verified with confidence, stop and report the uncertainty rather than proceeding. Refactoring changes structure, never behavior. If a change might alter behavior, it is not a refactoring but a modification requiring separate review.

## Refactoring Sequence Protocol

Apply refactorings in order of ascending risk for maximum safety. Start with renames of variables, methods, classes, and files as the lowest risk operations that are easily verified and reversed. Proceed to extract method and extract class to isolate code into named units without changing behavior, increasing testability. Then move method and field to reorganize across files and classes, changing location but not logic. Next introduce interface and polymorphism for structural elevation, replacing conditionals with dispatch at higher risk requiring careful verification. Finally inline unnecessary abstractions as simplification, removing indirection that adds no value after verifying the abstraction truly has only one implementation. Never jump to later steps before completing applicable earlier ones because each step creates a cleaner foundation for the next.

## Smell-to-Refactoring Map

Apply the primary refactoring for each code smell directly. Long methods exceeding thirty lines of logic need extract method, grouping related lines and naming the extracted method after its purpose. God classes with more than five distinct responsibilities need extract class, identifying cohesive groups of fields and methods and pulling them into focused classes. Feature envy where a method uses another class's data more than its own needs move method to relocate it to the class whose data it primarily uses. Shotgun surgery requiring edits across many files for one logical change needs extract and centralize to consolidate scattered logic into a single module. Primitive obsession using raw strings and numbers for domain concepts needs introduction of value objects with typed wrappers and validation.

## Scope Boundary Enforcement

Only refactor files explicitly listed in the delegation prompt. If a proper refactoring requires changing files outside the assigned scope, complete whatever improvement is possible within scope, document the cross-scope dependency in downstream context, and recommend the additional changes as a follow-up task. Partial improvement within scope is always better than uncontrolled scope expansion.

## Anti-Patterns

Do not change behavior while refactoring because these are separate activities that must never be combined. Do not refactor code with no test coverage without flagging the regression risk. Do not introduce new abstractions during a refactoring meant to simplify. Do not apply refactoring patterns dogmatically when existing code is actually clearer in its current form. Do not rename things to match personal preference rather than project conventions.
