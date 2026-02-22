<!--
Sync Impact Report
  Version change: N/A → 1.0.0 (initial creation)
  Modified principles: N/A (initial)
  Added sections: Inherited Standards, Core Principles (3), Governance
  Removed sections: N/A
  Templates requiring updates:
    - .specify/templates/plan-template.md ✅ (compatible — Constitution Check is generic)
    - .specify/templates/spec-template.md ✅ (compatible — no constitution references)
    - .specify/templates/tasks-template.md ✅ (compatible — test-first phasing aligns)
    - .specify/templates/checklist-template.md ✅ (compatible — no constitution references)
    - .specify/templates/agent-file-template.md ✅ (compatible — no constitution references)
    - .specify/templates/commands/*.md ✅ (none exist)
  Follow-up TODOs: None
-->

# twsrt Constitution

## Inherited Standards

This project inherits ALL development standards from the sources
below. This constitution does NOT duplicate their content — consult
them directly for full rules.

| Source | Path | Scope |
|--------|------|-------|
| Global Agent Instructions | `~/.claude/CLAUDE.md` | Code standards, TDD, debugging, git, naming, error handling, documentation |
| Development Standards | `~/dev/s/thoughts/development-standards.md` | Project types, build infrastructure (Makefile, VERSION, bump-my-version), CI/CD, language conventions (Rust, Python) |

When inherited standards conflict with this constitution, raise the
conflict with Tom before proceeding.

## Core Principles

The following principles are **gate criteria** for the speckit
planning workflow. Each synthesizes rules from inherited standards
into a checkable assertion.

### I. Test-First (NON-NEGOTIABLE)

TDD MUST be enforced. Write tests FIRST, verify they FAIL, then
implement. Red-Green-Refactor cycle. Failing tests MUST NOT be
deleted.

**Gate**: Every implementation plan MUST include test tasks that
precede their corresponding implementation tasks. Plans without
test-before-implement ordering MUST NOT pass the Constitution Check.

### II. Simplicity

YAGNI MUST be enforced. Make the smallest reasonable change. No
abstractions for one-time operations. No backward compatibility
without explicit approval. No features not needed now.

**Gate**: Every plan MUST justify any complexity beyond minimum
viable in the Complexity Tracking section. Plans with unjustified
abstractions, premature generalization, or speculative features
MUST NOT pass the Constitution Check.

### III. Project Standards Compliance

All project infrastructure MUST follow the patterns defined in
development-standards.md for the chosen project type (Python, Rust,
or Rust+Python hybrid). This includes directory layout, Makefile
structure, version management, CI/CD, and language-specific tooling.

**Gate**: The Technical Context section of every plan MUST identify
the project type and confirm infrastructure alignment with
development-standards.md. Deviations MUST be documented and approved.

## Governance

- This constitution establishes gate criteria for speckit plan
  approval. It does NOT override the inherited standards.
- Amendments require Tom's approval, version bump, and updated
  ratification date.
- Versioning follows SemVer: MAJOR for principle removal/redefinition,
  MINOR for new principle/section, PATCH for wording clarifications.
- All plans and reviews MUST verify compliance with these gate
  criteria before proceeding.

**Version**: 1.0.0 | **Ratified**: 2026-02-22 | **Last Amended**: 2026-02-22
