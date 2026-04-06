---
name: wcag-accessibility
category: constraint
description: >
  WCAG 2.1 AA accessibility constraint covering ARIA roles and properties, keyboard navigation,
  color contrast requirements, screen reader compatibility, and semantic HTML usage. Applied to
  any capability that produces or reviews user-facing interface code.
requires_tools: []
forbids_tools: []
archetypes:
  - builder
  - analyst
  - architect
  - investigator
primary_archetype: analyst
compatible_with:
  - accessibility-analysis
  - ux-design
  - code-writing
  - code-review
conflicts_with: []
requires: []
enhances:
  - accessibility-analysis
  - ux-design
temperature: 0.2
max_turns: 0
timeout_mins: 0
grounding_categories: []
grounding_priority: low
derived_from: []
version: 1.0.0
---

# WCAG Accessibility

All user-facing code must meet WCAG 2.1 Level AA conformance. Accessibility is a functional requirement, not an enhancement.

## Semantic HTML and ARIA

Use native HTML elements for their intended purpose: buttons for actions, links for navigation, headings for structure. Apply ARIA roles only when no native element provides the required semantics. Every custom widget must have an appropriate role, accessible name via aria-label or aria-labelledby, and state attributes as applicable. Live regions must specify politeness as polite or assertive.

## Keyboard Navigation

Every interactive element must be reachable and operable via keyboard alone. Maintain logical tab order matching visual layout. Custom widgets must follow WAI-ARIA Authoring Practices: arrow keys for composite navigation, Enter/Space for activation, Escape for dismissal. Never trap focus without an escape mechanism. Modals must constrain focus and return it to the trigger on close.

## Color and Visual Design

Minimum contrast ratio of 4.5:1 for normal text, 3:1 for large text. Never convey information through color alone. Focus indicators must have 3:1 contrast against adjacent colors. Respect prefers-reduced-motion by disabling non-essential animations.

## Screen Reader Compatibility

Provide alt text for non-decorative images; mark decorative images with alt="" and role="presentation". Form inputs must have programmatically associated labels. Group related controls with fieldset and legend. Associate error messages with inputs via aria-describedby. Data tables must use th with scope and caption elements.

## Content and Timing

Provide captions and transcripts for audio and video. Allow users to pause or hide auto-updating content. Do not impose time limits unless essential; when required, provide extension mechanisms.
