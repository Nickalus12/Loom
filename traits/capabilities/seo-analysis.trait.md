---
name: seo-analysis
category: capability
description: >
  Technical SEO assessment methodology covering crawlability auditing, meta tag completeness,
  structured data validation against schema.org, Core Web Vitals analysis, and schema markup
  selection. Prioritizes findings by actual search impact over theoretical best practices.
  Extracted from the seo_specialist agent definition.
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
  - accessibility-analysis
  - performance-analysis
  - content-strategy
conflicts_with: []
requires: []
enhances:
  - copywriting
  - content-strategy
temperature: 0.2
max_turns: 20
timeout_mins: 8
grounding_categories:
  - seo
  - analysis
grounding_priority: medium
derived_from:
  - seo_specialist
version: 1.0.0
---

# SEO Analysis

Analyze web-facing output for discoverability, crawlability, and search ranking factors through systematic auditing. Audit HTML output for meta tags, Open Graph, and Twitter Card completeness. Validate structured data against schema.org specifications. Assess Core Web Vitals implications from code patterns. Prioritize findings by actual search impact, not theoretical best practices.

## Crawlability Audit Protocol

Before reviewing content quality, verify search engines can discover and index pages. Parse robots.txt rules for all user-agents and flag overly broad disallow rules that block critical content. Check sitemap existence, XML validity, URL count versus actual page count, and lastmod accuracy. For each page, trace the canonical chain and flag chains longer than one hop, self-referencing canonicals pointing to non-200 pages, and conflicting canonical signals. Identify redirect chains longer than two hops, redirect loops, and soft 404s. Identify JavaScript-dependent content that may not be indexed by crawlers without JS execution. Classify findings by severity: critical for pages entirely blocked from indexing, major for pages indexable but with degraded signals, and minor for optimization opportunities.

## Schema Markup Selection

Choose structured data types based on primary content purpose. Product pages use the Product schema with name, image, description, and offers as required properties. Articles use the Article schema with headline, datePublished, and author. FAQ pages use FAQPage with mainEntity containing Question and Answer pairs. How-to guides use HowTo with name and step. Organization pages use Organization with name and url. Local business pages use LocalBusiness with name, address, and telephone. Event pages use Event with name, startDate, and location. Always validate against Google's Rich Results Test requirements because schema.org allows more properties than Google actually uses for rich results.

## Meta Tag Assessment

Audit every page for title tag presence and length between fifty and sixty characters, meta description presence and length between one hundred twenty and one hundred fifty-five characters, canonical tag correctness, robots meta directives, viewport configuration for mobile, and language attributes. Assess Open Graph completeness including og:title, og:description, og:image, and og:url. Validate Twitter Card tags. Check heading hierarchy from H1 through H6 for semantic structure ensuring each page has exactly one H1 and headings do not skip levels.

## Core Web Vitals Assessment

Assess code patterns that impact Core Web Vitals. For Largest Contentful Paint, check for render-blocking resources, unoptimized images without modern formats or responsive sizing, and missing preload hints for critical assets. For Cumulative Layout Shift, check for images and embeds without explicit dimensions, dynamically injected content above the fold, and font loading causing layout shifts. For Interaction to Next Paint, check for long-running JavaScript blocking the main thread, heavy event handlers without debouncing, and synchronous operations in interaction paths.

## Anti-Patterns

Do not recommend keyword stuffing or exact-match keyword density targets. Do not flag missing meta keywords tags which have been ignored by search engines since 2009. Do not recommend structured data types that do not match the page's actual content purpose. Do not treat all pages as equally important for SEO. Do not suggest SEO changes that degrade user experience.
