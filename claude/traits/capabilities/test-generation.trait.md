---
name: test-generation
category: capability
description: >
  Test strategy and implementation methodology covering the test pyramid, AAA pattern, edge case
  discovery, test isolation, mock boundary rules, and test type selection. Focuses on tests that
  catch real bugs and document expected behavior. Extracted from the tester agent definition.
requires_tools:
  - read_file
  - write_file
  - replace
  - run_shell_command
  - grep_search
  - glob
forbids_tools: []
archetypes:
  - builder
primary_archetype: builder
compatible_with:
  - code-writing
  - debugging
  - security-analysis
conflicts_with: []
requires: []
enhances:
  - code-writing
  - debugging
temperature: 0.2
max_turns: 25
timeout_mins: 10
grounding_categories:
  - testing
  - quality
grounding_priority: high
derived_from:
  - tester
version: 1.0.0
---

# Test Generation

Write tests that catch real bugs and document expected behavior. Follow the test pyramid with many unit tests, fewer integration tests, and minimal end-to-end tests. Use the Arrange-Act-Assert pattern consistently and test behavior rather than implementation details.

## Test Strategy Selection

Choose the right test type based on what is being tested. Unit tests cover pure functions, business logic, data transformations, edge cases, and error handling branches. They are fast, isolated, and deterministic, forming the bulk of the test suite. Integration tests cover database queries against actual databases, API endpoints with middleware chains, service-to-service interactions, and message queue producers and consumers. They are slower and require setup and teardown. End-to-end tests cover critical user journeys only such as login flow, checkout flow, and core business workflows. They should be minimal in count and maximum in coverage of the critical path. Never end-to-end test what a unit test can cover. Regression tests reproduce a specific reported bug, with the test name referencing the bug or ticket, verifying the exact input that triggered the bug now produces correct output.

## Edge Case Discovery Protocol

For every function under test, systematically check applicable categories. Empty inputs: null, undefined, empty string, empty array, empty object, zero, NaN. Boundary values: minimum valid, maximum valid, minimum minus one, maximum plus one, exactly at threshold. Type boundaries: MAX_SAFE_INTEGER, negative numbers, floating point precision issues, very long strings. Invalid states: expired tokens, closed connections, missing configuration, revoked permissions, concurrent modifications. Collections: empty collection, single element, many elements, duplicate elements, null elements within collection. Select the categories relevant to the function's input types and domain rather than applying every category to every function.

## Test Isolation Checklist

Every test must create its own test data with no dependence on shared fixtures that other tests might modify. Every test must clean up side effects or use transactions and sandboxes that roll back automatically. Mock external services at the system boundary using HTTP clients, not internal functions. Every test must produce the same result regardless of execution order with no implicit dependency on other tests running first. No test should read from or write to shared mutable state including module-level variables, singletons, or global configuration. If a test fails when run in isolation but passes in a suite or vice versa, it has an isolation defect that must be fixed before the test is considered valid.

## Mock Boundary Rule

Mock at system boundaries only. Mock external HTTP APIs, databases in unit tests, file system, system clock, random number generators, and email or SMS services. Never mock internal classes, internal functions, private methods, value objects, or domain entities. If mocking an internal dependency is required to make a function testable, the function has a design problem of tight coupling or hidden dependency. Report it as a finding rather than papering over it with mocks.

## Testing Standards

Use descriptive test names following the pattern "should expected behavior when condition". Maintain one assertion per test or closely related assertions. Ensure test isolation with no shared mutable state between tests. Mock at boundaries, not internals. Cover edge cases including null, undefined, empty collections, boundary values, and concurrent access. Test error paths verifying error messages, codes, and recovery.

## Anti-Patterns

Do not test implementation details by checking that a specific private method was called N times instead of verifying correct output. Do not use snapshot tests for dynamic content because they are fragile and provide little behavioral insight. Do not use test names that describe code structure instead of behavior. Do not share mutable state between tests through module-level variables or singletons. Do not write tests that pass even when the code under test is broken.
