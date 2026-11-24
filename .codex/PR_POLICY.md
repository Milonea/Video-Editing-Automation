# Pull Request and Merge Policy

## Routine changes

Routine code, test, and documentation changes may merge automatically when the current pull request head has passed the required aggregate CI check, the branch is mergeable, the pull request is not a draft, and no blocking label or unresolved review thread exists.

Routine changes do not require a separate user approval at each commit, push, pull request, or merge step. Record the evidence in the pull request and keep the user-facing report concise.

## Manual gates

Do not auto-merge a change while any of these conditions applies:

- The change needs a user decision about product behavior or an ambiguous requirement.
- A security, credential, access-control, privacy, or data-loss risk is unresolved.
- A database or data migration is destructive or has no verified rollback.
- A paid external service, live account, production deployment, or external write is part of the requested outcome and has not been explicitly authorized.
- A required hardware, host-application, legal, or live-service check is essential to prove correctness and has not been completed.
- The pull request has an explicit blocking label, failing or unavailable required check, merge conflict, or unresolved review thread.

If a manual check is only needed for release readiness, separate it from code merge when the code can be safely isolated, feature-gated, and validated without that live check. Mark release readiness accurately.

## Protected project-control files

Changes to agent instructions, policy, permissions, CI workflows, repository settings, or project profiles require a dedicated policy-integrity check. That check must confirm the change does not weaken the repository's declared safety boundaries or remove required validation. Keep the result visible as part of the single aggregate CI status.

This baseline does not require multiple sequential agent approvals for the same evidence. A specialized reviewer may provide additional findings, but the merge decision must be represented by one clear pass/fail gate and any explicit manual blocker.

## Required merge evidence

Before merge, confirm all of the following on the latest head SHA:

- Required local and hosted checks have passed.
- The pull request targets the expected default branch and is mergeable.
- No blocking label, unresolved review thread, or required manual gate remains.
- The change is within the task scope and does not include unrelated or sensitive files.

Prefer GitHub auto-merge after these conditions are represented by required status checks. If repository settings or account-plan limits prevent auto-merge, follow the safe fallback documented in AGENTS.md. Never treat missing check data as success.
