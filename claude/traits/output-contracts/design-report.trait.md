---
name: design-report
category: output-contract
description: >
  Structured output format for architecture and API design tasks. Covers problem statement,
  requirements, approach with alternatives considered, architecture diagram, component interfaces,
  and risk assessment.
requires_tools: []
forbids_tools: []
archetypes:
  - architect
primary_archetype: architect
compatible_with:
  - architecture-design
  - api-design
conflicts_with: []
requires: []
enhances: []
temperature: 0.0
max_turns: 0
timeout_mins: 0
grounding_categories: []
grounding_priority: low
derived_from: []
version: 1.0.0
---

# Design Report

Upon completing an architecture or design task, produce a report in the following exact format. Every section is required.

## Required Output Format

```markdown
## Problem Statement
[One to three sentences describing the problem being solved and why the current state is insufficient]

## Requirements

### Functional Requirements
1. [Requirement with measurable acceptance criteria]
2. [Requirement with measurable acceptance criteria]

### Non-Functional Requirements
1. [Performance, scalability, reliability, or security requirement with quantitative target]
2. [Constraint from existing system, team, or infrastructure]

## Approach

### Selected Design
[Description of the chosen architecture or design with rationale]

### Alternatives Considered

#### Alternative 1: [Name]
- **Description**: [Brief description]
- **Pros**: [Advantages]
- **Cons**: [Disadvantages]
- **Rejection Reason**: [Why this was not selected]

#### Alternative 2: [Name]
- **Description**: [Brief description]
- **Pros**: [Advantages]
- **Cons**: [Disadvantages]
- **Rejection Reason**: [Why this was not selected]

## Architecture

### Component Diagram
[ASCII or Mermaid diagram showing components and their relationships]

### Data Flow
[Description of how data moves through the system for primary use cases]

## Component Interfaces

### [Component Name]
- **Responsibility**: [Single responsibility statement]
- **Interface**:
  ```typescript
  interface ComponentName {
    methodName(param: Type): ReturnType;
  }
  ```
- **Dependencies**: [What this component requires]
- **Consumers**: [What depends on this component]

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| [Risk description] | Low/Medium/High | Low/Medium/High | [Mitigation strategy] |

## Implementation Plan
1. [Phase or step with deliverable and estimated scope]
2. [Phase or step with deliverable and estimated scope]
```

## Formatting Rules

The Problem Statement must be concise and must not restate the requirements. Requirements must have measurable acceptance criteria or quantitative targets, never vague statements like "should be fast." At least two alternatives must be considered and documented with explicit rejection reasons. Component interfaces must use typed signatures in the project's primary language. The Risk Assessment must include at least three identified risks with concrete mitigation strategies. The Implementation Plan must order steps by dependency so that no step depends on an unfinished later step.
