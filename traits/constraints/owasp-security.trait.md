---
name: owasp-security
category: constraint
description: >
  OWASP Top 10 security constraint enforcing injection prevention, authentication best practices,
  data exposure prevention, security misconfiguration hardening, and cross-site attack awareness.
  Applied as a cross-cutting concern to any capability that produces or reviews code handling
  user input, authentication, or sensitive data.
requires_tools: []
forbids_tools: []
archetypes:
  - builder
  - analyst
  - architect
  - investigator
primary_archetype: analyst
compatible_with:
  - security-analysis
  - code-writing
  - code-review
  - api-design
conflicts_with: []
requires: []
enhances:
  - security-analysis
  - code-review
temperature: 0.2
max_turns: 0
timeout_mins: 0
grounding_categories: []
grounding_priority: low
derived_from: []
version: 1.0.0
---

# OWASP Security

All code that handles user input, authentication, authorization, or sensitive data must comply with the OWASP Top 10 risk categories.

## Injection Prevention

Parameterize all database queries using prepared statements or ORM query builders. Never concatenate user input into SQL, LDAP, OS commands, or XPath expressions. Validate input type, length, and range before use. Apply allowlist validation over denylist. Escape output for the rendering context: HTML entity encoding for bodies, attribute encoding for attributes, JavaScript encoding for scripts, URL encoding for parameters.

## Authentication and Session Management

Store passwords using bcrypt, scrypt, or Argon2id. Generate session tokens with CSPRNG at minimum 128 bits of entropy. Set cookies with Secure, HttpOnly, and SameSite=Strict. Implement account lockout with exponential backoff. Invalidate sessions on logout, password change, and privilege escalation.

## Sensitive Data Exposure

Encrypt sensitive data at rest using AES-256-GCM. Enforce TLS 1.2+ for data in transit. Never log credentials, tokens, PII, or payment card data. Mask sensitive fields in API responses. Disable caching for sensitive responses via Cache-Control headers.

## Security Misconfiguration and Access Control

Apply least privilege to all service accounts, API keys, and roles. Disable default credentials, unnecessary HTTP methods, directory listings, and debug endpoints in production. Validate authorization server-side on every request. Rate-limit authentication endpoints and sensitive operations.

## Cross-Site Attack Awareness

Set Content-Security-Policy headers restricting script sources. Sanitize user-supplied URLs to prevent SSRF, rejecting internal network addresses and metadata endpoints. Apply anti-CSRF tokens to state-changing operations. Encode dynamic HTML output to prevent XSS. Validate redirect URLs against an allowlist.
