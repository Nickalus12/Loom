---
name: debugging
category: capability
description: >
  Systematic root cause analysis methodology covering hypothesis-driven investigation, evidence
  classification, bisection strategy, log analysis, and execution path tracing. Focuses on
  verified conclusions over speculation. Extracted from the debugger agent definition.
requires_tools:
  - read_file
  - run_shell_command
  - grep_search
  - glob
  - list_directory
forbids_tools: []
archetypes:
  - builder
  - investigator
primary_archetype: investigator
compatible_with:
  - code-writing
  - test-generation
conflicts_with: []
requires: []
enhances:
  - code-writing
  - test-generation
temperature: 0.2
max_turns: 20
timeout_mins: 8
grounding_categories:
  - investigation
  - diagnostics
grounding_priority: medium
derived_from:
  - debugger
version: 1.0.0
---

# Debugging

Investigate defects through hypothesis-driven methodology. Follow a structured process of reproduction, hypothesis formation, investigation, isolation, verification, and reporting. Never propose a fix before confirming root cause with sufficient evidence.

## Investigation Methodology

Begin by understanding the expected versus actual behavior to establish a clear reproduction case. Form two to three most likely root causes based on symptoms. Trace execution flow, examine logs, and inspect state to gather evidence. Narrow down to the specific code path and condition causing the defect. Confirm the root cause explains all observed symptoms. Document findings with evidence and a recommended fix.

## Hypothesis Ranking Protocol

After forming hypotheses for the root cause, rank them by three criteria. Symptom coverage: how many observed symptoms does the hypothesis explain, with more coverage ranking higher. Change recency: how recently was the suspected code area modified, with more recent changes ranking higher, verified through git log. Path simplicity: how complex is the code path involved, with simpler paths checked first because they fail in simpler, more obvious ways. Investigate hypotheses in rank order. Abandon a hypothesis after two pieces of contradicting evidence. If all hypotheses are eliminated, form new ones based on evidence gathered during investigation.

## Bisection Strategy

When the failure point is unclear, identify the last known good state and the first known bad state. Use git log on suspected files to find changes between good and bad states. If reproduction is cheap at under one minute, use binary search on commits by testing the midpoint and narrowing the range. If reproduction is expensive, use git diff between good and bad states to identify candidate changes, then trace each. Bisection is most effective when the failure is deterministic and the reproduction steps are clear.

## Evidence Classification

Tag every piece of evidence gathered during investigation. Confirming evidence directly supports the hypothesis and would be expected if the hypothesis is true. Contradicting evidence directly weakens the hypothesis and would not be expected if the hypothesis is true. Neutral evidence provides context but no signal. A root cause conclusion requires minimum three confirming pieces of evidence, zero contradicting pieces of evidence, and the root cause must explain all observed symptoms without exception.

## Log Analysis Protocol

Search for the exact error message verbatim in logs first. Widen to the surrounding time window of thirty seconds before the error and ten seconds after. Correlate across log sources including application logs, database slow query logs, and infrastructure logs. Identify the earliest anomaly in the timeline because it is closer to the root cause than the reported error. Look for patterns: does the error repeat, is it time-correlated with specific times of day, is it load-correlated.

## Anti-Patterns

Do not propose a fix before confirming root cause with sufficient evidence of minimum three confirming and zero contradicting pieces. Do not investigate only the file where the error surfaces instead of tracing the execution path upstream to origin. Do not treat correlation as causation. Do not stop investigation after the first plausible explanation without verifying it accounts for all observed symptoms. Do not modify code during investigation because debugging is read-only analysis and fixes come after root cause is confirmed.
