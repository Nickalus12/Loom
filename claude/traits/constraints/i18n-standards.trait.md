---
name: i18n-standards
category: constraint
description: >
  Internationalization standards constraint covering ICU message format, plural rules, RTL layout
  support, locale file structure, string extraction practices, and date/number/currency formatting.
  Applied to any capability that produces or reviews code with user-visible text or locale-sensitive
  data formatting.
requires_tools: []
forbids_tools: []
archetypes:
  - builder
  - analyst
  - architect
  - investigator
primary_archetype: builder
compatible_with:
  - i18n-implementation
  - code-writing
conflicts_with: []
requires: []
enhances:
  - i18n-implementation
temperature: 0.2
max_turns: 0
timeout_mins: 0
grounding_categories: []
grounding_priority: low
derived_from: []
version: 1.0.0
---

# Internationalization Standards

All user-visible text and locale-sensitive data formatting must support internationalization from initial implementation, not as a retrofit.

## ICU Message Format and Plural Rules

Use ICU MessageFormat syntax for all translatable strings containing variables, plurals, or selection logic. Never concatenate translated fragments. Define plural categories using CLDR rules: zero, one, two, few, many, other. Use select for gender-dependent text and selectordinal for ordinals. Keep message identifiers stable and semantic with dot-notation namespaces.

## Locale File Structure and String Extraction

Store translations in JSON or YAML organized by BCP 47 locale code. Maintain one file per locale with identical key structures. Never embed translatable strings in source code. Provide context comments for ambiguous strings. Flag untranslatable terms. Implement fallback chains: requested locale to language-only locale to default.

## Date, Number, and Currency Formatting

Use the Intl API or equivalent locale-aware libraries for all date, number, and currency display. Never concatenate date strings. Store dates in UTC; convert to user timezone and locale format at the display layer. Format numbers with locale-appropriate separators. Display currency with correct symbol position and precision per locale. Use ISO 4217 codes internally.

## RTL and Bidirectional Text Support

Set dir attribute dynamically based on active locale. Use CSS logical properties: inline-start/end instead of left/right, block-start/end instead of top/bottom. Mirror layouts for RTL locales. Handle bidirectional text with Unicode control characters or the bdi element for user-generated content.
