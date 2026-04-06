---
name: solid-principles
category: constraint
description: >
  SOLID design principles constraint enforcing Single Responsibility, Open/Closed, Liskov
  Substitution, Interface Segregation, and Dependency Inversion in all produced code. Applied
  as a cross-cutting concern to capabilities that create, modify, or review object-oriented
  or module-based code.
requires_tools: []
forbids_tools: []
archetypes:
  - builder
  - analyst
  - architect
  - investigator
primary_archetype: builder
compatible_with:
  - code-writing
  - refactoring
  - code-review
  - architecture-design
conflicts_with: []
requires: []
enhances:
  - code-writing
  - refactoring
temperature: 0.2
max_turns: 0
timeout_mins: 0
grounding_categories: []
grounding_priority: low
derived_from: []
version: 1.0.0
---

# SOLID Principles

All code must adhere to the five SOLID principles. These are not aspirational guidelines but hard constraints that every class, module, and function must satisfy.

## Single Responsibility Principle

Each class, module, or function must have exactly one reason to change. Extract each concern into its own unit: controllers handle request/response mapping, services handle business logic, repositories handle data access. When a class requires changes for two unrelated feature requests, it has multiple responsibilities and must be split.

## Open/Closed Principle

Modules must be open for extension but closed for modification. Use strategy patterns, plugin architectures, or dependency injection to add behavior without changing existing code. When a requirement would modify a switch or if-else chain, introduce a polymorphic interface instead.

## Liskov Substitution Principle

Subtypes must be substitutable for their base types without altering correctness. A subclass must not strengthen preconditions, weaken postconditions, or throw unexpected exceptions. Prefer composition over inheritance when a subtype cannot fulfill the full behavioral contract of the parent.

## Interface Segregation Principle

No client should depend on methods it does not use. Split large interfaces into focused ones aligned with specific client needs. Separate read from write operations, query from command interfaces. Each consumer depends only on the interface slice it actually calls.

## Dependency Inversion Principle

High-level modules must not depend on low-level modules; both depend on abstractions. Inject dependencies through constructors or factories rather than direct instantiation. Business logic depends on repository interfaces, not concrete database clients. Wiring happens at the composition root, enabling testing with stubs and swapping implementations.
