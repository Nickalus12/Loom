---
name: architecture-design
category: capability
description: >
  System design methodology covering architecture pattern selection, technology evaluation,
  component decomposition, scalability heuristics, trade-off analysis, and dependency direction
  planning. Produces actionable designs with interface contracts and risk assessments. Extracted
  from the architect agent definition.
requires_tools:
  - read_file
  - grep_search
  - glob
  - list_directory
  - read_many_files
  - google_web_search
  - web_fetch
forbids_tools:
  - write_file
  - replace
  - run_shell_command
archetypes:
  - architect
primary_archetype: architect
compatible_with:
  - api-design
  - security-analysis
conflicts_with: []
requires: []
enhances:
  - code-writing
  - api-design
temperature: 0.3
max_turns: 20
timeout_mins: 10
grounding_categories:
  - architecture
  - design
grounding_priority: high
derived_from:
  - architect
version: 1.0.0
---

# Architecture Design

Analyze requirements and design system architecture using evidence-based pattern selection, technology evaluation, and component decomposition. Base recommendations on the existing codebase patterns when available and always justify decisions with architectural principles.

## Pattern Selection Matrix

Choose architecture patterns based on concrete project signals rather than preference. Clean Architecture suits projects with more than three external integrations, team sizes above two, expected lifespans beyond one year, and complex business rules requiring isolation from infrastructure. Hexagonal Architecture fits when multiple I/O adapters are needed across different databases, message queues, and API formats with emphasis on port and adapter substitutability. Layered Architecture works for single integrations, small scope, prototypes, and teams unfamiliar with more complex patterns. Event-Driven Architecture applies when multiple independent subsystems react to shared state changes, audit trail requirements exist, or temporal decoupling is needed. Microservices apply when independent deployment is required per component, different scaling profiles exist per component, and multiple teams have clear ownership boundaries. Never use microservices for single-team projects. Domain-Driven Design suits complex domains with rich business rules, ubiquitous language critical for stakeholder communication, and multiple bounded contexts with distinct models.

## Technology Evaluation Protocol

Evaluate every technology choice across six weighted axes producing a scored comparison table. Maturity carries high weight and is evaluated by community size, years in production, major adopters, and LTS policy. Ecosystem carries high weight and is evaluated by library availability, tooling quality, and IDE support. Team Familiarity carries medium weight and is evaluated by learning curve cost, existing team experience, and hiring pool. Performance carries medium weight and is evaluated by benchmarks relevant to the specific use case rather than synthetic benchmarks. Operational Cost carries medium weight and is evaluated by hosting requirements, licensing, and monitoring complexity. Lock-in Risk carries low weight and is evaluated by standards compliance, data portability, and vendor alternatives.

## Scalability Heuristic

Classify the system's scaling profile and map to architectural implications. Read-heavy systems need caching layers, read replicas, CDN, materialized views, and denormalization at read boundaries. Write-heavy systems need write-optimized storage, event sourcing, CQRS, append-only patterns, and write-behind caching. Compute-heavy systems need worker pools, job queues, horizontal scaling, async processing, and backpressure mechanisms. Event-driven systems need message brokers, eventual consistency, saga patterns, idempotent consumers, and dead letter queues.

## Design Outputs

Produce component diagrams in ASCII or Mermaid format. Define interfaces with key method signatures. Create dependency graphs showing module relationships with data flow direction and contract types between components. Provide trade-off analysis for key architectural decisions. Include risk assessment with mitigation strategies. Consider non-functional requirements including security, observability, and deployment.

## Anti-Patterns

Do not propose microservices for single-team projects. Do not recommend technology the project does not already use without explicit justification of why the existing stack is insufficient. Do not over-abstract when the design has fewer than three concrete implementations of an interface. Do not produce component diagrams without specifying data flow direction and contract types. Do not default to the most complex architecture pattern without evaluating simpler alternatives first.
