# Contributing

The repository lifecycle is defined in AGENTS.md and .codex/WORKFLOW.md. Project-specific commands, personas, and data boundaries belong in .codex/PROJECT_PROFILE.md.

Routine changes follow this path:

1. Inspect existing work and the current default branch.
2. Make a scoped change on a task branch.
3. Run relevant project checks and the required pull request workflow.
4. Commit and push the task branch, then create or update its pull request.
5. Merge after all required checks pass and no manual gate remains.
6. Verify the merged default branch and report the result.

Keep the pull request small enough to review as one logical change. Split unrelated changes into separate pull requests.
