---
name: compliance-review
category: capability
description: >
  Regulatory compliance assessment methodology covering geographic scope determination, data type
  classification, data flow privacy auditing, consent mechanism evaluation, and open-source license
  compatibility checking. Maps applicable regulations to concrete compliance gaps with specific
  regulatory references. Extracted from the compliance_reviewer agent definition.
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
  - analyst
primary_archetype: analyst
compatible_with:
  - security-analysis
  - documentation-writing
  - devops-operations
conflicts_with: []
requires:
  - gdpr-compliance
enhances:
  - security-analysis
  - documentation-writing
temperature: 0.3
max_turns: 15
timeout_mins: 5
grounding_categories:
  - compliance
  - privacy
grounding_priority: high
derived_from:
  - compliance_reviewer
version: 1.0.0
---

# Compliance Review

Identify regulatory compliance gaps through systematic regulatory mapping, not generic checklists. Determine which regulations apply based on user geography, data types collected, business model, and industry vertical. Provide actionable remediation grounded in specific regulatory articles. Distinguish between legal requirements and best practices. Present findings as technical compliance gaps requiring legal review, never as legal advice.

## Regulatory Scope Assessment

Determine applicable regulations in four steps. First assess geographic scope: EU and EEA users trigger GDPR regardless of company location, California users trigger CCPA if revenue, data volume, or revenue-from-selling thresholds are met, UK users trigger UK GDPR, Brazil triggers LGPD, Canada triggers PIPEDA, and any EU-accessible website setting cookies triggers the ePrivacy Directive. Second assess data types: identity data follows standard processing rules, authentication data requires encryption at rest and triggers breach notification, financial data requires PCI DSS, health data is GDPR special category requiring explicit consent with potential HIPAA applicability, biometric data is special category with potential BIPA applicability, location data requires purpose limitation and opt-out for precise geolocation, and children's data requires age verification and parental consent. Third assess business model impacts: advertising-supported requires cookie consent and CCPA opt-out, SaaS B2B requires Data Processing Agreements, e-commerce requires PCI DSS, and data monetization triggers CCPA sale provisions. Fourth compile an applicability matrix summarizing which regulations apply, why, and their key requirements.

## Data Flow Privacy Audit

Trace personal data through its entire lifecycle. Map every collection point documenting data collected, lawful basis under GDPR, consent mechanism, and disclosure. Trace each data element through processing documenting storage location, processing purposes, third parties receiving data, retention period, deletion mechanism, and cross-border transfers. Audit every third-party service that receives personal data verifying Data Processing Agreement status, SCC compliance for EU-US transfers, privacy policy disclosure, and user opt-out capability. Verify data subject rights implementation by testing access, rectification, erasure, portability, objection, and opt-out of sale mechanisms against actual implementation, not just policy claims.

## Cookie and Consent Assessment

Evaluate cookie consent implementation against ePrivacy requirements. Consent must be affirmative and not just notice. Consent must be granular with per-category control for strictly necessary, analytics, functional, and marketing cookies. Pre-checked boxes are not valid consent. Users must be able to change preferences at any time, not just at first visit. Consent records must be stored as proof. Third-party cookies must be inventoried with purpose documentation.

## License Compliance Audit

Identify open-source licenses in the dependency tree. Verify attribution requirements per license type for MIT, Apache, and BSD. Assess copyleft obligations for GPL, LGPL, and AGPL. Check license compatibility between dependencies. Identify commercial license restrictions.

## Anti-Patterns

Do not assume GDPR only applies to EU companies because territorial scope is based on data subject location. Do not treat cookie consent as a one-time banner without preference management. Do not recommend generic privacy policies without mapping to actual data practices. Do not ignore third-party SDK data collection in compliance assessment. Do not confuse Data Processing Agreements with privacy policies because they serve different purposes and have different requirements.
