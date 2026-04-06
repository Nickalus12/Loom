---
name: devops-operations
category: capability
description: >
  Infrastructure automation methodology covering CI/CD pipeline stage ordering, container
  optimization, secret management classification, deployment strategies, and rollback readiness
  verification. Builds reproducible, observable, and self-healing deployment systems. Extracted
  from the devops_engineer agent definition.
requires_tools:
  - read_file
  - write_file
  - replace
  - run_shell_command
  - grep_search
forbids_tools: []
archetypes:
  - builder
primary_archetype: builder
compatible_with:
  - security-analysis
  - performance-analysis
  - data-engineering
conflicts_with: []
requires: []
enhances:
  - code-writing
  - security-analysis
temperature: 0.2
max_turns: 20
timeout_mins: 8
grounding_categories:
  - infrastructure
  - deployment
grounding_priority: high
derived_from:
  - devops_engineer
version: 1.0.0
---

# DevOps Operations

Design and implement infrastructure automation, CI/CD pipelines, and deployment systems that are reproducible, observable, and self-healing. Never hardcode secrets or credentials. Always include health checks in containerized services. Design for rollback capability in every deployment.

## Pipeline Stage Ordering Protocol

Every CI/CD pipeline follows this stage order, never running slow stages before fast ones. Install dependencies with cache restoration from lockfile hash. Lint and format check for fast fail catching style issues in seconds. Type check and compile to catch structural errors before tests run. Unit tests for fast high-signal feedback. Build artifacts only after tests pass to avoid wasting build time on broken code. Integration tests run slower against built artifacts. Security scan for dependency audit and static analysis. Deploy to staging only after all quality gates pass. Smoke tests verify deployment health against staging. Deploy to production as the final stage requiring all prior stages green. Stages one through four should complete in under five minutes for fast feedback. Never deploy without at least the first five stages passing.

## Container Optimization

Select base images by need. Full OS tooling for debugging uses debian-slim, not full debian or ubuntu. Language runtime only uses official slim variants. Static binaries from Go or Rust use scratch or distroless. Required practices include multi-stage builds with build stage having dev dependencies and runtime stage without, non-root user creation and switching to application user, explicit COPY only with never using ADD for local files due to implicit behavior, a dockerignore mirroring gitignore plus node_modules and build artifacts and test files, and pinning base image digests in production Dockerfiles for reproducibility.

## Secret Management Classification

Classify secrets by sensitivity and handle accordingly. Critical secrets including API keys, database credentials, and encryption keys use external vault with runtime injection via sidecar or init container, never in environment variables which are visible in process listings, and rotated on schedule. High sensitivity secrets including service tokens and webhook secrets use CI/CD platform secret storage injected as environment variables at deploy time and masked in logs. Low sensitivity items including public API keys and feature flags use environment variables in deployment manifests and can be checked into the repository if truly non-sensitive. Secrets must never appear in source code, baked into Docker images, committed to git history, printed in log output, or passed as CLI arguments.

## Rollback Readiness Checklist

Every deployment must satisfy: database migrations are backward-compatible so new code works with old schema and old code works with new schema. Previous container images are retained and tagged for rollback with minimum three previous versions. Rollback procedure is documented and has been tested in staging. Feature flags gate new user-facing behavior where possible. Health check endpoints detect application-level failures within thirty seconds. Monitoring alerts are configured for error rate spikes post-deployment.

## Anti-Patterns

Do not deploy without health check endpoints that verify application-level readiness beyond just port availability. Do not use latest tag for base images or dependencies in production. Do not run CI steps depending on external services without timeout and retry configuration. Do not store secrets as CI/CD environment variables visible in build logs. Do not create pipelines taking over fifteen minutes without parallelizing independent stages.
