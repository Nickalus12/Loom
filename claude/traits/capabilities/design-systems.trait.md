---
name: design-systems
category: capability
description: >
  Design system engineering methodology covering token hierarchy design, component API contract
  definition, theming architecture, CSS methodology selection, and visual regression strategy.
  Bridges design intent and code implementation ensuring visual consistency and developer
  ergonomics. Extracted from the design_system_engineer agent definition.
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
  - ux-design
  - accessibility-analysis
  - code-writing
conflicts_with: []
requires: []
enhances:
  - ux-design
  - code-writing
  - accessibility-analysis
temperature: 0.2
max_turns: 25
timeout_mins: 10
grounding_categories:
  - design
  - implementation
grounding_priority: high
derived_from:
  - design_system_engineer
version: 1.0.0
---

# Design Systems

Build the foundational layer bridging design intent and code implementation. Define design token hierarchies, component API contracts, and theming systems ensuring visual consistency, developer ergonomics, and maintainable style architecture. All visual values including colors, spacing, typography, shadows, borders, and radii must flow through tokens with no magic numbers in component code.

## Token Hierarchy Design

Design a layered token system scaled to project size. Small projects with fewer than ten components use primitive and semantic layers to provide naming consistency without over-engineering. Medium projects with ten to fifty components use primitive, semantic, and selective component tokens only for heavily themed components. Large design systems with fifty or more components and multi-brand requirements use all three layers for brand theming, white-labeling, and independent component customization. Primitive tokens are raw context-free values forming the palette, named by category, scale, and step such as color.blue.500 and spacing.4. Semantic tokens are purpose-mapped values referencing primitives that encode design intent, named by category, usage context, and variant such as color.bg.primary and color.text.link. Component tokens are scoped overrides for specific components enabling per-component theming, named by component, property, and state such as button.bg.hover.

## Component API Contract Design

Design consistent ergonomic APIs that promote correct usage. Prefer variant enums over booleans because boolean props create combinatorial explosion while enums are explicit. Separate concerns into distinct props rather than overloading a single prop. Use children for content rather than label props. Default to the most common usage so the zero-config version handles eighty percent of cases. Expose className and style escape hatches for one-off overrides. Forward refs to the root DOM element for focus management and measurement. Enumerate all visual and behavioral variants per component with every axis having a default value and mutually exclusive values.

## Theming Architecture

Define the theme as a typed contract that all themes must implement covering color, spacing, radius, shadow, and font categories. Every theme including light, dark, high-contrast, and brand variants must satisfy the full shape with missing values treated as build errors not runtime fallbacks. Choose the appropriate composition pattern: single components with props for simple one-element components, compound components with slots for medium-complexity two to three element components, and render props or headless hooks for complex dynamic-children components. Start with the simplest pattern that satisfies the use case.

## Accessibility Requirements

Every component API contract must specify its accessibility requirements including ARIA role, required attributes, and keyboard pattern. Buttons need aria-disabled and aria-pressed for toggles with Enter and Space activation. Inputs need aria-required, aria-invalid, and aria-describedby. Modals need aria-modal and aria-labelledby with Escape to close and trapped focus. Dropdown menus need aria-expanded and aria-haspopup with arrow key navigation. No component ships without its accessibility contract satisfied.

## Anti-Patterns

Do not skip the token layer and hardcode values directly in components because global theme changes become impossible. Do not design component APIs with boolean props instead of variant enums. Do not build a design system without consumer input. Do not over-engineer token granularity for small projects. Do not ignore existing CSS architecture when introducing tokens but integrate with the existing methodology.
