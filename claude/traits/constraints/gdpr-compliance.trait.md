---
name: gdpr-compliance
category: constraint
description: >
  GDPR compliance constraint covering data minimization, consent management, right to erasure,
  data portability, privacy by design, DPO requirements, and breach notification obligations.
  Applied to any capability that produces or reviews code handling personal data of EU residents.
requires_tools: []
forbids_tools: []
archetypes:
  - builder
  - analyst
  - architect
  - investigator
primary_archetype: analyst
compatible_with:
  - compliance-review
  - security-analysis
  - api-design
conflicts_with: []
requires: []
enhances:
  - compliance-review
temperature: 0.2
max_turns: 0
timeout_mins: 0
grounding_categories: []
grounding_priority: low
derived_from: []
version: 1.0.0
---

# GDPR Compliance

All systems processing personal data of EU residents must comply with the General Data Protection Regulation. Privacy is a design constraint, not a feature added before launch.

## Data Minimization and Purpose Limitation

Collect only personal data strictly necessary for the stated purpose. Document the lawful basis for each field: consent, contract, legal obligation, vital interests, public task, or legitimate interests. Implement retention policies that auto-delete or anonymize data once the purpose expires. Do not repurpose data without separate consent.

## Consent Management

Obtain consent through clear, affirmative action with no pre-checked boxes. Record consent with timestamp, privacy notice version, specific purposes, and data subject identity. Provide withdrawal mechanisms as easy as granting. When withdrawn, cease processing and delete data if no other lawful basis applies.

## Data Subject Rights Implementation

Implement Right of Access returning all personal data in structured, machine-readable format. Implement Right to Erasure with cascading deletion across all data stores, backups, third-party processors, and search indices. Implement Right to Portability providing data in JSON or CSV with a documented schema. Implement Right to Rectification through self-service or documented request process. Respond to all requests within thirty calendar days.

## Privacy by Design

Apply pseudonymization wherever full personal data is not required. Restrict personal data visibility to roles that require it. Log all access with accessor identity, timestamp, and purpose. Conduct Data Protection Impact Assessments for profiling, large-scale sensitive data processing, or systematic monitoring. Encrypt personal data at rest and in transit.

## Breach Notification

Monitor and alert on unauthorized access to personal data stores. Notify the supervisory authority within seventy-two hours of breach awareness. Notify affected data subjects without undue delay when high risk to rights and freedoms exists. Maintain a breach register with nature, affected subjects count, consequences, and remediation measures.
