# Project Agent Instructions

## Source of project-specific rules

Use .codex/PROJECT_PROFILE.md for the project's purpose, technology stack, personas, validation commands, data boundaries, and external side effects. Persona and role settings may vary by project. They do not expand Git, security, or external-service permissions.

## Standing development authority

For routine repository work, Codex is authorized to investigate, implement, run relevant checks, update required project documentation, commit, push a task branch, create or update a pull request, and merge after all required automated gates pass. Do not ask for a separate confirmation at each step.

Keep user-visible review in GitHub: provide a clear pull request with concise evidence, then report its final status. Stop for a decision only when the requested outcome or authority is genuinely unclear, a required manual gate cannot be completed, or an action crosses a boundary in .codex/PR_POLICY.md.

## Git safety

- Before editing, inspect the current branch, working tree, remotes, open pull requests, and existing local or remote work.
- Preserve unrelated changes. Never include or discard them without authorization.
- Use a task branch and pull request. Do not push directly to the default branch.
- Do not force-push, rewrite published history, or run destructive Git commands.
- Commit only scoped files. Exclude secrets, credentials, personal data, user media, local absolute paths, and generated build output unless the project explicitly requires a safe fixture.
- Check the configured Git author identity before the first commit. Use the account's configured noreply address when available. Never rewrite existing commits merely to change author metadata.
- If a remote branch or pull request already represents this task, verify ownership and resume it instead of creating duplicate work.

## Validation and pull requests

- Follow .codex/PROJECT_PROFILE.md for project commands and the smallest relevant test set.
- Run directly affected checks first, then all checks required by the pull request workflow.
- Do not report an unrun check as passing.
- Keep one aggregate validation result for routine pull requests. Do not require several separate agent approvals when they inspect the same evidence.
- Create the pull request as ready when its required gates are complete. Keep it draft only while a specific manual gate or unresolved implementation issue remains.
- Update the changelog, release notes, or status document only when the project profile or repository convention requires it.

## Merge and completion

Prefer repository auto-merge after the required checks pass. If auto-merge is unavailable, use direct merge only when the repository policy explicitly permits it and the same current-head checks, risk gates, and review-thread checks have passed. Never use a merge fallback to bypass a failed or unavailable check.

After merging, verify the expected commit is on the default branch, run the required post-merge check, and confirm the worktree is clean. Report the commit, pull request, checks, and any remaining manual or external gate.
