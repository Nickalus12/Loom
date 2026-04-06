---
name: content-strategy
category: capability
description: >
  Content planning methodology covering content gap analysis, editorial priority matrix, audience
  segment mapping, keyword cluster research, and content governance. Defines what content gets
  created, for whom, and why, aligning content production with business goals and audience needs.
  Extracted from the content_strategist agent definition.
requires_tools:
  - read_file
  - grep_search
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
  - copywriting
  - seo-analysis
  - analytics-engineering
conflicts_with: []
requires: []
enhances:
  - copywriting
  - seo-analysis
temperature: 0.3
max_turns: 15
timeout_mins: 5
grounding_categories:
  - content
  - strategy
grounding_priority: medium
derived_from:
  - content_strategist
version: 1.0.0
---

# Content Strategy

Plan and recommend content aligned with business goals and audience needs. Map target audience segments with their information needs and journey stage. Analyze existing content for gaps, redundancies, and opportunities. Prioritize content by expected impact using search volume, conversion potential, and competitive gap. Establish content governance including voice guidelines, update cadence, and ownership.

## Content Gap Analysis

Follow a systematic approach to identifying content opportunities. First inventory all existing content with URL, title, topic, format, word count, last updated, and traffic if available. Second perform audience mapping by listing the top ten questions for each target persona at each journey stage of awareness, consideration, and decision. Third build a coverage matrix mapping existing content against audience questions to identify unanswered questions as gaps, multiple answers for one question as redundancy, and outdated answers as staleness. Fourth conduct a competitive scan checking top three competitors for topics they cover that the project does not. Fifth prioritize gaps by scoring audience demand based on search volume or question frequency multiplied by business alignment based on proximity to conversion multiplied by competitive difficulty based on how hard it is to rank.

## Editorial Priority Matrix

Prioritize content creation using impact and effort. High business impact with low effort items are quick wins including FAQ pages and product comparisons to do first. High business impact with high effort items are comprehensive guides, pillar content, and case studies to plan carefully. Low business impact with low effort items are nice-to-have evergreen content to do if capacity permits. Low business impact with high effort items should be deprioritized or skipped. Business impact equals proximity to conversion action multiplied by audience size. Effort equals research depth plus production complexity plus review requirements.

## Audience Segment Mapping

For each target persona, define information needs at each journey stage. Awareness stage users need educational content explaining the problem space and establishing authority. Consideration stage users need comparison content, how-to guides, and case studies showing solution approaches. Decision stage users need product-specific content, pricing information, implementation details, and social proof. Map content types to stages: blog posts and educational content serve awareness, guides and comparisons serve consideration, product pages and case studies serve decision.

## Content Governance

Establish governance rules for sustainable content operations. Define voice guidelines ensuring consistency across all content creators. Set update cadence per content type specifying how often each piece should be reviewed and refreshed. Assign ownership so every content piece has a responsible party for accuracy and freshness. Define the editorial workflow from brief through draft, review, publish, and measurement with clear responsibilities at each stage.

## Anti-Patterns

Do not recommend content topics based solely on keyword volume without considering search intent or business alignment. Do not plan content without defining the target audience segment and journey stage. Do not create editorial calendars without accounting for production capacity and review cycles. Do not recommend content formats without considering the team's actual production capabilities. Do not treat all content as equally important because ruthless prioritization is essential.
