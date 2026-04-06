---
name: i18n-implementation
category: capability
description: >
  Internationalization engineering methodology covering locale architecture design, string
  extraction protocols, pluralization using CLDR categories, RTL support with CSS logical
  properties, and date/number/currency formatting. Ensures applications can be translated without
  code changes. Extracted from the i18n_specialist agent definition.
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
  - accessibility-analysis
  - ux-design
conflicts_with: []
requires: []
enhances:
  - code-writing
  - accessibility-analysis
temperature: 0.2
max_turns: 20
timeout_mins: 8
grounding_categories:
  - internationalization
  - implementation
grounding_priority: medium
derived_from:
  - i18n_specialist
version: 1.0.0
---

# i18n Implementation

Architect and implement internationalization that separates content from code, handling the full spectrum of locale-specific formatting. Audit codebases for i18n readiness including hardcoded strings, locale-dependent formatting, concatenated text, and culturally-specific assumptions. Follow the project's existing i18n setup if one exists and never introduce a competing library.

## Locale Architecture Design

Systematically choose library, file format, key naming convention, and directory structure. Select libraries by framework: react-intl or react-i18next for React, vue-i18n for Vue, angular localize or ngx-translate for Angular, next-intl for Next.js App Router, and FormatJS for framework-agnostic projects. Choose file format by translation workflow: JSON flat or nested for developer-managed translations with excellent programmatic access, ICU MessageFormat JSON for complex pluralization requiring ICU-aware TMS, PO/POT for established translation workflows with universal TMS support, and XLIFF for enterprise CAT tool integration. Use feature-based key naming with the pattern feature.element.qualifier for applications with distinct user flows and component-based naming for component libraries. Use locale-first directory structure for fewer than ten locales and namespace-first for more than ten.

## String Extraction Protocol

Scan the codebase for translatable strings by priority. Critical priority: UI labels including button text, form labels, headings, and navigation items, plus error messages for validation and API errors. High priority: placeholder text, notifications, metadata including page titles and meta descriptions, alt text, and formatted content with locale-dependent dates, numbers, and currencies. Medium priority: email and notification templates. Skip developer strings including log messages and debug output. When extracting strings with dynamic values, convert to the library's interpolation syntax with descriptive variable names, never positional placeholders. Provide translator context for every extracted string including character limits, gender context, screenshot references, and plurality requirements.

## Pluralization and Formatting

Implement pluralization using CLDR categories of zero, one, two, few, many, and other rather than simplistic singular/plural because Arabic has six forms. Configure date, number, and currency formatting using the Intl API or framework-specific formatters, never hardcoding formats like MM/DD/YYYY which is US-only or using period as decimal separator which varies by locale. Accommodate text expansion of thirty to two hundred percent across languages in UI layouts by using flexible layouts and testing with pseudo-localization.

## RTL Support

Implement bidirectional text support for RTL locales using CSS logical properties with inline-start and inline-end instead of left and right. Mirror layouts for RTL reading direction. Handle icon direction considering that some icons like arrows should mirror while others like checkmarks should not. Never hardcode text alignment. Test with pseudo-localization that inflates string length and simulates RTL direction.

## Anti-Patterns

Do not concatenate translated strings to form sentences because word order varies by locale. Do not hardcode date, number, or currency formats. Do not use string length for UI layout calculations. Do not extract strings without providing translator context. Do not ignore bidirectional text requirements by using CSS left/right instead of logical properties.
