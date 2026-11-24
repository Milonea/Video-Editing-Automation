# Development Workflow

## 1. Inspect

Read AGENTS.md and .codex/PROJECT_PROFILE.md. Check the default branch, current branch, dirty files, worktrees, remotes, and open pull requests. Reuse an existing task branch or pull request when it belongs to the current task.

## 2. Plan a bounded change

Record the intended outcome, files or components in scope, excluded areas, relevant checks, and any rollback step. Split independent features, broad refactors, and unrelated documentation into separate changes.

## 3. Implement and validate

Make the smallest change that satisfies the request. Run checks from the project profile that cover the affected behavior, followed by the required CI checks. Preserve user changes and report every skipped or unavailable check.

## 4. Record project documentation

Update user-facing documentation, changelog, or status only when the project profile requires it. Avoid copying the same progress state into multiple documents.

## 5. Commit and open a pull request

Check the Git author identity and diff, then commit only the scoped files on a task branch. Push the branch and create or update one pull request with the repository template.

## 6. Complete the merge

Inspect checks, current head SHA, mergeability, draft status, labels, requested reviews, and unresolved review threads. Use repository auto-merge when available. Otherwise follow the safe direct-merge policy in AGENTS.md. Never merge a stale head or skip an unresolved manual gate.

## 7. Verify after merge

Confirm the merged commit is present on the default branch. Run the project profile's required post-merge validation and check that the worktree is clean before reporting completion.
