# Codex Project Baseline

Reusable starting files for a repository where Codex owns routine development from implementation through a validated pull request and merge.

## Files

- AGENTS.md: default authority, Git safety, validation, and completion rules.
- CONTRIBUTING.md: short entry point for developers and agents.
- .codex/WORKFLOW.md: the repeatable implementation-to-merge lifecycle.
- .codex/PR_POLICY.md: automated merge criteria and genuine manual gates.
- .codex/PROJECT_PROFILE.template.md: project-specific stack, personas, commands, and boundaries.
- .github/pull_request_template.md: concise evidence for each change.
- .github/CI_SETUP.template.md: checklist for adding a stack-specific required CI workflow.

## Install in a new project

1. Copy the baseline files into the new repository.
2. Copy PROJECT_PROFILE.template.md to PROJECT_PROFILE.md and fill in the real stack, commands, data boundaries, personas, and manual checks.
3. Add a GitHub Actions workflow that runs those real checks on pull requests. Use pinned action commit SHAs and grant only the permissions each workflow needs.
4. Protect the default branch, require the single aggregate validation check, and enable auto-merge where the account plan and permissions support it.
5. Test the complete flow with a small documentation-only PR and a small code PR before using it for larger work.

Do not activate the example CI policy until the project-specific commands and required check name are real. Do not copy persona names, external-service rules, or stack assumptions from another project.

For existing repositories, inventory open PRs, branches, and uncommitted work first. Preserve existing work and handle it separately from installing this baseline.
