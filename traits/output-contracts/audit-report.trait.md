---
name: audit-report
category: output-contract
description: >
  Structured output format for audit and compliance tasks. Covers executive summary, scope,
  methodology, categorized findings, risk matrix, and remediation roadmap. Used for security
  audits, accessibility audits, compliance reviews, and SEO assessments.
requires_tools: []
forbids_tools: []
archetypes:
  - analyst
primary_archetype: analyst
compatible_with:
  - security-analysis
  - accessibility-analysis
  - compliance-review
  - seo-analysis
conflicts_with: []
requires: []
enhances: []
temperature: 0.0
max_turns: 0
timeout_mins: 0
grounding_categories: []
grounding_priority: low
derived_from: []
version: 1.0.0
---

# Audit Report

Upon completing an audit or compliance assessment, produce a report in the following exact format. Every section is required.

## Required Output Format

```markdown
## Executive Summary
[Three to five sentences summarizing the audit scope, overall posture, critical findings count, and top recommendation. Written for a non-technical stakeholder.]

## Scope
- **Systems Assessed**: [List of repositories, services, or components audited]
- **Assessment Date**: [Date or date range]
- **Methodology**: [Framework or standard applied: OWASP Top 10, WCAG 2.1 AA, GDPR Article references, etc.]
- **Out of Scope**: [Explicitly excluded areas]

## Findings by Category

### [Category Name] (e.g., Authentication, Data Exposure, Keyboard Navigation)

#### [F1] [Finding title]
- **Severity**: Critical | High | Medium | Low | Informational
- **Location**: `path/to/file.ext:line` or [System component]
- **Description**: [What was found]
- **Evidence**: [Proof: code snippet, screenshot description, or test result]
- **Impact**: [Business or user impact if unaddressed]
- **Recommendation**: [Specific remediation action]
- **Reference**: [Standard clause: OWASP A01, WCAG 1.1.1, GDPR Art. 17, etc.]

## Risk Matrix

| ID | Finding | Severity | Likelihood | Impact | Risk Score |
|----|---------|----------|-----------|--------|------------|
| F1 | [Title] | Critical | High | High | Critical |
| F2 | [Title] | Medium | Medium | High | High |

## Remediation Roadmap

### Immediate (0-7 days)
- [ ] [F1] [Remediation action for critical findings]

### Short-term (7-30 days)
- [ ] [F2] [Remediation action for high-severity findings]

### Medium-term (30-90 days)
- [ ] [F3] [Remediation action for medium-severity findings]

### Long-term (90+ days)
- [ ] [F4] [Remediation action for low-severity and improvement items]

## Compliance Summary
| Requirement | Status | Notes |
|------------|--------|-------|
| [Standard clause] | Pass / Fail / Partial / N/A | [Brief explanation] |
```

## Formatting Rules

Findings are numbered sequentially with the F prefix across all categories. Each finding must reference the specific standard clause it violates. The Risk Matrix must include every finding. Severity uses five levels: Critical, High, Medium, Low, Informational. The Remediation Roadmap must assign every finding to a time horizon based on its severity and business impact. The Compliance Summary table must cover all assessed requirements from the applied methodology, not just failures. The Executive Summary must be understandable without reading the detailed findings.
