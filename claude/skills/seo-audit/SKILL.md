---
name: seo-audit
description: Run a Loom-style SEO assessment for meta tags, structured data, crawlability, and Core Web Vitals
argument-hint: "[URL or file paths]"
allowed-tools: Read, Glob, Grep, Bash(*), Agent
---


# Loom SEO Audit

Read `${CLAUDE_PLUGIN_ROOT}/references/architecture.md`.

## Protocol

Before delegating, activate the `delegation` skill to ensure agent-base-protocol and filesystem-safety-protocol are injected into the delegation prompt.

## Workflow

1. Define the SEO audit scope.
2. Identify web-facing output files (HTML, templates, routes).
3. Audit meta tags, schema markup, crawlability, and Core Web Vitals.
4. Present findings with severity, location, and remediation guidance.
5. Offer to apply remediations if approved.

## Constraints

- Present findings before proposing remediation.
- Do not modify code without explicit user approval.
