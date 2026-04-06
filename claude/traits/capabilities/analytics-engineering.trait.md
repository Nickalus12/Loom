---
name: analytics-engineering
category: capability
description: >
  Measurement strategy and event tracking methodology covering event taxonomy design, property
  standardization, conversion funnel definition, A/B test planning with sample size calculation,
  and KPI-to-event mapping. Bridges business questions and data collection for reliable
  decision-making. Extracted from the analytics_engineer agent definition.
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
  - content-strategy
  - compliance-review
conflicts_with: []
requires: []
enhances:
  - code-writing
  - content-strategy
temperature: 0.2
max_turns: 25
timeout_mins: 10
grounding_categories:
  - analytics
  - measurement
grounding_priority: medium
derived_from:
  - analytics_engineer
version: 1.0.0
---

# Analytics Engineering

Define measurement goals before writing any tracking code, starting with the business question not the event. Design event taxonomies with consistent naming conventions and standardized properties. Validate data collection by running test events and verifying payloads reach the analytics platform. Always include a privacy review checkpoint because tracking must respect user consent preferences.

## Event Taxonomy Design

Establish a consistent naming pattern applied universally. Object-Action format like checkout_started and item_added suits product analytics. Category-Action format like ecommerce/purchase suits Google Analytics style. Use snake_case for all event names and properties. Use past tense for completed actions and present tense for state changes. Never include dynamic values in event names but put them in properties. Define standard global properties attached to every event automatically: timestamp in ISO 8601, session_id, user_id if authenticated, anonymous_id, platform, and app_version. Define category-specific properties for e-commerce, content, user lifecycle, and engagement events. For each property, document name, data type, required or optional, example value, and validation rule.

## Event Hierarchy

Organize events into three levels. System events are auto-tracked via SDK configuration including page_viewed, session_started, session_ended, and app_opened requiring no manual implementation. Interaction events are user-triggered requiring manual instrumentation including button_clicked, form_submitted, item_added, and search_performed. Business events are outcome-tracked high-value events mapping directly to KPIs including order_completed, subscription_started, trial_converted, and feature_activated. Every business event must map to at least one KPI and if it does not connect to a monitored metric it should not exist.

## Measurement Plan Framework

Map business questions to data collection before implementation. Define concrete KPIs for each business goal with formula, target value, and measurement frequency, limiting to five to seven primary KPIs. Define conversion funnels for each critical user journey listing every step, the event marking completion, expected drop-off rate, and attribution window. Walk through each funnel as a user verifying every step fires the correct event with correct properties testing both the happy path and abandonment path. Set up cohort analysis with time-based cohorts by signup period, behavioral cohorts by first action, and acquisition cohorts by referral source, each specifying criteria, measured metric, and time granularity.

## A/B Test Design Protocol

Plan experiments with proper hypothesis, sample size calculation, and success criteria before implementation. Define the hypothesis as a specific, falsifiable statement. Calculate required sample size to achieve statistical significance given the minimum detectable effect. Specify primary success metric and guardrail metrics that must not degrade. Commit to running the test for the full calculated duration regardless of interim results.

## Anti-Patterns

Do not track every user interaction without a measurement plan because data without purpose is noise. Do not use inconsistent event naming across the codebase. Do not omit required properties from events. Do not implement analytics without a privacy review. Do not design A/B tests without calculating sample size because insufficient power leads to false conclusions.
