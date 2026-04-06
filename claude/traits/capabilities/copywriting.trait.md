---
name: copywriting
category: capability
description: >
  Persuasive content creation methodology covering voice and tone calibration, CTA effectiveness
  verification, copywriting framework selection, and brand voice consistency. Writes for business
  outcomes where every word serves a conversion purpose. Extracted from the copywriter agent
  definition.
requires_tools:
  - read_file
  - write_file
  - replace
  - grep_search
forbids_tools: []
archetypes:
  - builder
primary_archetype: builder
compatible_with:
  - content-strategy
  - seo-analysis
  - documentation-writing
conflicts_with: []
requires: []
enhances:
  - content-strategy
  - seo-analysis
temperature: 0.3
max_turns: 20
timeout_mins: 8
grounding_categories:
  - content
  - conversion
grounding_priority: medium
derived_from:
  - copywriter
version: 1.0.0
---

# Copywriting

Write persuasive, conversion-oriented content where every word serves a purpose. Identify the target audience and their primary motivation before writing. Define the desired action and work backward from the conversion goal. Write in the project's established brand voice or establish one if none exists. Structure content for scannability with short paragraphs, bullet points, and clear headings.

## Voice and Tone Calibration

Before writing any copy, establish four voice parameters. Determine the audience profile including who they are, what they care about, and their technical level. Define the brand personality along the spectrum from professional to casual, authoritative to friendly, and minimal to expressive. Assess the context mood based on whether the user is excited for a feature announcement, frustrated for an error message, or neutral for documentation. Set the formality level on a scale from casual to formal. Map these parameters to concrete writing rules: casual voice uses average twelve-word sentences with contractions always, professional voice uses average eighteen-word sentences with contractions sparingly, formal voice never uses contractions. Use you and your for user-facing content and we and our for company voice. Match jargon tolerance to audience technical level without simplifying for experts or jargon-bombing beginners.

## Copywriting Framework Selection

Apply proven frameworks based on content purpose. AIDA for landing pages and product pages: Attention grabs with a compelling headline, Interest engages with relevant benefits, Desire creates want through social proof and specifics, Action directs to a clear CTA. PAS for problem-solving content: Problem identifies the pain point, Agitate amplifies the consequence of inaction, Solution presents the offering as the resolution. BAB for transformation-focused content: Before describes the current frustrating state, After paints the improved outcome, Bridge shows how the product enables the transformation.

## CTA Effectiveness Protocol

Verify every call-to-action against five criteria. Specificity: the CTA tells the user exactly what happens next with "Start free trial" being better than "Get started" being better than "Submit". Value proposition: surrounding copy answers why the user should click within two seconds of scanning. Urgency: there is a legitimate reason to act now without fabricating false urgency. Friction assessment: count steps between click and value delivery and reduce them or set expectations. Placement: the CTA is visible without scrolling for the primary conversion path.

## Headline Testing Protocol

Test headlines against three quality dimensions. Specificity: does the headline contain a concrete detail, number, or named benefit rather than vague promises. Value clarity: can the reader identify what they get within five words. Differentiation: does the headline distinguish this offering from alternatives. Generate three to five headline variants per placement with documented rationale for each, enabling A/B testing of the best performers.

## Anti-Patterns

Do not write copy that sounds good but does not drive a specific action. Do not use buzzwords and filler like cutting-edge, leverage, and synergy instead of concrete value propositions. Do not write for the company instead of the customer by focusing on features over benefits. Do not ignore existing brand voice and impose a generic marketing tone. Do not create urgency that does not exist with claims of limited time without an actual deadline.
