---
name: api-design
category: capability
description: >
  Contract-first API design methodology covering resource-oriented endpoint design, request/response
  schema definition, pagination strategy selection, error taxonomy construction, and versioning
  policies. Produces implementable API contracts with schemas and examples. Extracted from the
  api_designer agent definition.
requires_tools:
  - read_file
  - grep_search
  - glob
  - google_web_search
forbids_tools:
  - write_file
  - replace
  - run_shell_command
archetypes:
  - architect
primary_archetype: architect
compatible_with:
  - architecture-design
  - documentation-writing
  - code-writing
conflicts_with: []
requires: []
enhances:
  - code-writing
  - documentation-writing
temperature: 0.3
max_turns: 15
timeout_mins: 5
grounding_categories:
  - api
  - design
grounding_priority: high
derived_from:
  - api_designer
version: 1.0.0
---

# API Design

Design resource-oriented APIs using a contract-first approach. Define endpoint catalogs, request/response schemas, error contracts, and versioning strategies before any implementation begins. Follow existing API patterns in the codebase when present, prioritizing consistency and predictability over cleverness.

## Endpoint Design Protocol

For each resource, identify the noun using plural form for collections and singular for singletons. Map CRUD operations to HTTP methods: GET for retrieval, POST for creation, PUT for full replacement, PATCH for partial update, DELETE for removal. Determine resource relationships using nested routes for strong ownership and flat routes with query filters for loose association. Place identity in path parameters, filtering in query parameters, and mutation payloads in request bodies. Define a consistent response envelope with data, meta for pagination, and errors fields. Every endpoint must specify its authentication requirement and rate limiting policy.

## Pagination Strategy Selection

Choose pagination based on collection size. Collections under one hundred records need no pagination. Collections under ten thousand records use offset-based pagination with page and limit parameters including total count. Collections under one million records use cursor-based pagination without total count because counting is expensive at scale. Collections over one million records use cursor-based with keyset pagination. Always enforce page size limits with a maximum of one hundred and a default of twenty. Include link headers or next and previous cursors in every paginated response.

## Error Taxonomy Construction

Map domain errors to HTTP status codes with machine-readable contracts. Use 400 for validation errors with field-level details. Use 401 for authentication failures. Use 403 for authorization failures. Use 404 for missing resources without distinguishing not-found from no-access for security. Use 409 for state conflicts including concurrent modification and duplicate creation. Use 422 for business rule violations with valid syntax but domain rule failures. Every error response must include a machine-readable code as a string enum, a human-readable message, and an optional details object with field-level information.

## Versioning Strategy

Use URL path versioning for breaking changes as the most explicit and easiest to route approach. Use header versioning only when the project already uses it. Never mix versioning strategies within the same API. Define breaking changes explicitly: removing fields, changing field types, removing endpoints, and changing authentication requirements all constitute breaking changes requiring a version increment.

## Anti-Patterns

Do not design endpoints that expose internal database model structure directly. Do not use inconsistent pluralization across resource names. Do not use POST for operations that are idempotent and should be PUT or PATCH. Do not omit rate limiting and pagination from the API contract. Do not design RPC-style endpoints instead of resource-oriented REST.
