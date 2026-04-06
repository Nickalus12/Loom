---
name: ux-design
category: capability
description: >
  User-centered interaction design methodology covering interaction pattern selection, usability
  heuristic evaluation, user flow mapping, information architecture, and progressive disclosure.
  Translates user goals into concrete interface specifications that developers can implement.
  Extracted from the ux_designer agent definition.
requires_tools:
  - read_file
  - grep_search
  - glob
  - google_web_search
forbids_tools:
  - write_file
  - replace
  - run_shell_command
archetypes:
  - analyst
primary_archetype: analyst
compatible_with:
  - accessibility-analysis
  - design-systems
  - content-strategy
conflicts_with: []
requires: []
enhances:
  - accessibility-analysis
  - design-systems
  - copywriting
temperature: 0.2
max_turns: 20
timeout_mins: 8
grounding_categories:
  - design
  - usability
grounding_priority: medium
derived_from:
  - ux_designer
version: 1.0.0
---

# UX Design

Translate user goals and business requirements into concrete interface structures, user flows, and interaction specifications. Identify user goals, mental models, and task context before proposing any interface. Map user journeys from entry point to task completion, identifying decision points and potential drop-offs. Validate designs against Nielsen's usability heuristics before handoff.

## Interaction Pattern Selection

Choose UI patterns based on task type and context. Identify the task type first: data entry for forms and wizards, data consumption for tables and dashboards, navigation for menus and search, decision-making for comparisons and filters, or object manipulation for CRUD interfaces and drag-and-drop. Then evaluate context factors. For field count, use single-page forms for one to six fields and multi-step wizards for seven or more. For data volume, use card grids or simple lists under fifty items and virtualized tables with sort and filter above fifty. For navigation depth, use flat tabs for two to five sections and sidebar navigation with hierarchy for six or more. For user expertise, use guided flows with defaults and tooltips for novices and power-user interfaces with keyboard shortcuts for experts. Validate that the pattern matches platform conventions, allows task completion in three clicks or fewer, degrades gracefully on smaller screens, and is the simplest pattern achieving the goal.

## Usability Heuristic Evaluation

Evaluate interfaces against Nielsen's ten heuristics systematically. Visibility of system status checks for loading indicators, progress bars, confirmation messages, and real-time validation, with critical severity if the user cannot tell whether their action succeeded. Match between system and real world checks that labels use domain language, icons are recognizable, and data formats match expectations. User control and freedom checks for undo availability, cancel and back buttons, clear exit from modals, and draft autosave. Consistency and standards checks that the same action uses the same pattern everywhere. Error prevention checks for confirmation on destructive actions, input constraints, disabled states, and inline validation. Recognition over recall checks for labels on form fields rather than placeholder-only, recent selections, and preserved context. Flexibility and efficiency checks for keyboard shortcuts and bulk operations. Aesthetic minimalism checks that every element serves a purpose. Error recovery checks that messages state what went wrong and suggest corrective action. Help and documentation checks for contextual guidance near complex fields.

## Severity Classification

Critical findings block task completion or cause data loss and must be fixed before launch. Major findings cause significant friction or confusion and should be fixed in the current iteration. Minor findings are suboptimal but functional and should be fixed when capacity allows.

## Progressive Disclosure

Design for showing only what the user needs at each step. Specify interaction states for every component including default, hover, focus, active, disabled, loading, error, empty, and success states. Define information architecture with content hierarchy, navigation structure, and page-level layout that reveals complexity progressively rather than overwhelming users upfront.

## Anti-Patterns

Do not design interfaces without first understanding user goals, task frequency, and expertise level. Do not create complex navigation hierarchies for simple tasks. Do not ignore mobile-first responsive design. Do not break established platform conventions without strong justification. Do not add features without offsetting the increased cognitive load with simplifications elsewhere.
