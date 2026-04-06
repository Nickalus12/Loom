---
name: security-analysis
category: capability
description: >
  Security assessment methodology covering attack surface mapping, data flow taint tracking,
  STRIDE threat modeling, OWASP Top 10 vulnerability detection, dependency auditing, and
  vulnerability verification with proof-of-concept evidence. Extracted from the security_engineer
  agent definition.
requires_tools:
  - read_file
  - grep_search
  - glob
  - list_directory
  - read_many_files
  - google_web_search
  - web_fetch
forbids_tools: []
archetypes:
  - analyst
  - builder
primary_archetype: analyst
compatible_with:
  - code-review
  - code-writing
  - test-generation
conflicts_with: []
requires:
  - owasp-security
enhances:
  - code-review
  - code-writing
temperature: 0.2
max_turns: 20
timeout_mins: 8
grounding_categories:
  - security
  - compliance
grounding_priority: high
derived_from:
  - security_engineer
version: 1.0.0
---

# Security Analysis

Identify vulnerabilities through systematic analysis using attack surface mapping, data flow tracing, and threat modeling. Prioritize findings by actual exploitability, not theoretical risk.

## Attack Surface Mapping Protocol

Before reviewing any code, map all entry points in the application. Catalog HTTP endpoints with method, path, authentication requirement, and input parameters across path, query, body, and headers. Identify message queue consumers with queue name, message schema, and authentication. Document scheduled jobs with trigger schedule, input sources, and privilege level. Map file upload handlers with accepted types, size limits, storage destination, and processing pipeline. List CLI commands with arguments, environment variable inputs, and privilege requirements. Prioritize review by exposure level: public unauthenticated endpoints first as highest risk, then public authenticated endpoints requiring stolen credentials, then internal service-to-service endpoints requiring network access, then admin-only endpoints requiring privileged credentials.

## Data Flow Taint Tracking

For each entry point, trace user-controlled input through every transformation until it reaches a sink. Identify all user-controlled input at the entry point. Follow the data through each function call, assignment, and transformation. At each step determine whether the data is validated, sanitized, or encoded for the output context. Identify the sink type: database query, file system operation, shell command, HTTP response body, log output, or email content. Verify that sanitization matches the sink type because HTML encoding does not prevent SQL injection. A finding exists only when tainted data reaches a sink without appropriate sanitization for that specific sink type.

## Vulnerability Verification Protocol

For every potential vulnerability, identify the exact input that would trigger it. Trace the input path from entry point to vulnerable sink, confirming no sanitization exists. Assess reachability by determining whether an external attacker can actually reach the code path and through what entry point. Assess impact by determining the actual damage if exploited, whether data breach, privilege escalation, denial of service, or information disclosure. Classify severity based on actual exploitability and impact, not theoretical worst case. Theoretical vulnerabilities behind multiple layers of authentication, authorization, and input validation are not Critical.

## Dependency Audit Methodology

Check lock files for known CVEs using available scanning tools. For each CVE found, determine whether the vulnerable function or code path is actually called by the project. Check if the vulnerability is in a direct dependency or transitive. Transitive vulnerabilities with no direct usage path are lower priority. Reachable CVEs become actionable findings with remediation priority based on severity. Unreachable CVEs become informational findings to document but not classify as actionable.

## Anti-Patterns

Do not report theoretical vulnerabilities without demonstrating a reachable attack path from an entry point to the vulnerable sink. Do not flag dependency CVEs without checking whether the vulnerable code path is actually used. Do not recommend security controls that already exist in the codebase. Do not classify all findings as Critical. Do not report TLS configuration issues without checking whether the application handles TLS or a reverse proxy terminates it.
