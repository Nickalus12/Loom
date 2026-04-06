---
name: accessibility-analysis
category: capability
description: >
  WCAG compliance assessment methodology covering conformance level selection, semantic HTML
  verification, ARIA role selection protocol, keyboard navigation testing, and color contrast
  verification. Identifies accessibility barriers through systematic auditing beyond automated
  scanner output. Extracted from the accessibility_specialist agent definition.
requires_tools:
  - read_file
  - grep_search
  - run_shell_command
  - google_web_search
forbids_tools:
  - write_file
  - replace
archetypes:
  - analyst
primary_archetype: analyst
compatible_with:
  - ux-design
  - code-review
  - design-systems
conflicts_with: []
requires:
  - wcag-accessibility
enhances:
  - ux-design
  - code-writing
temperature: 0.2
max_turns: 20
timeout_mins: 8
grounding_categories:
  - accessibility
  - compliance
grounding_priority: high
derived_from:
  - accessibility_specialist
version: 1.0.0
---

# Accessibility Analysis

Identify accessibility barriers through systematic WCAG auditing, not automated scanner output alone. Review semantic HTML structure for correct element usage before assessing ARIA. Test keyboard navigation paths including tab order, focus management, escape handling, and skip links. Verify color contrast ratios for all text and interactive elements. Automated tools catch approximately thirty percent of WCAG issues so manual testing is required.

## WCAG Conformance Level Selection

Determine the target conformance level based on project context. Government, public sector, healthcare, education, and financial services projects require WCAG 2.1 AA minimum due to legal mandates. E-commerce with over ten million annual revenue should target WCAG 2.1 AA based on ADA Title III precedent. General public audience applications should target AA because fifteen to twenty percent of the population has a disability. Internal tools with fewer than fifty users and no known accessibility needs target Level A minimum with AA aspirational. New projects should target AA from the start because retrofitting costs five to ten times more. Existing projects with no accessibility work should achieve Level A first then plan AA remediation by priority.

## ARIA Role Selection Protocol

The first rule of ARIA is do not use ARIA if a native HTML element achieves the same result. Check for semantic HTML first: use button elements not div with role button, use a href not role link, use nav not role navigation, use h1 through h6 not role heading with aria-level. For custom interactive components, select the correct composite role: dropdown menus use role menu with menuitem, tab interfaces use tablist with tab and tabpanel, accordions use region with button triggers, comboboxes use combobox with listbox and option, tree views use tree with treeitem, sliders use role slider with valuemin, valuemax, and valuenow, and toggles use role switch or checkbox. Validate every ARIA usage: does removing the attribute break screen reader comprehension, is the label actually descriptive, does keyboard behavior match the ARIA Authoring Practices Guide, are all required states and properties present, and is aria-hidden used only on decorative elements never on focusable elements.

## Assessment Dimensions

Audit against four WCAG principles. Perceivable: text alternatives for non-text content, captions and audio descriptions, sufficient color contrast at 4.5 to 1 for normal text and 3 to 1 for large text, adaptable content, and distinguishable foreground from background. Operable: all functionality via keyboard, sufficient time for interactions, no seizure-causing content, navigable structure, and input modalities beyond keyboard. Understandable: readable and predictable content, consistent navigation, and input assistance with error prevention. Robust: valid HTML, complete name role value for all UI components, and programmatically determinable status messages.

## Severity Classification

Critical findings block task completion or cause complete access barriers for users with disabilities and must be fixed before launch. Major findings cause significant friction requiring workarounds and should be fixed in the current iteration. Minor findings are suboptimal but still usable and should be fixed when capacity allows. Classify each finding with its WCAG criterion reference, affected user group, and specific remediation pattern.

## Anti-Patterns

Do not use ARIA roles when equivalent semantic HTML elements exist. Do not test only with mouse interactions because keyboard-only testing reveals focus traps and unreachable elements. Do not treat accessibility as a post-launch checkbox. Do not rely solely on automated scanning tools. Do not add tabindex values greater than zero to fix focus order because positive tabindex creates unpredictable focus across the page so the DOM order should be fixed instead.
