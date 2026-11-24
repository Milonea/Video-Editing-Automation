# CI Setup Checklist

This file is guidance, not an active GitHub Actions workflow. Create a real workflow only after confirming the project-specific commands.

## Required workflow behavior

- Run on pull requests to the default branch.
- Run the same essential checks on pushes to the default branch.
- Use read-only repository permissions for validation jobs.
- Pin third-party actions to reviewed full commit SHAs.
- Use the real install, test, lint, typecheck, or build commands from .codex/PROJECT_PROFILE.md.
- Include a documentation or format check so documentation-only changes receive meaningful validation.
- Publish one stable aggregate check that can be required by branch rules.
- Keep any merge-writing job separate from untrusted pull-request code and give it only the required write permissions.
- Skip draft PR merge jobs without marking validation as failed.
- Treat missing check data as blocked, not passed.

Before enabling auto-merge, verify that the required check is reported consistently on a small documentation PR and a small code PR. Do not make auto-merge depend on an optional or path-filtered check that disappears for some changes.

If the GitHub plan or connection does not support branch rules or required checks, document that limit and use a local pre-merge gate that verifies the exact PR head SHA. Do not enable a direct-merge fallback that ignores failed or unavailable checks.
