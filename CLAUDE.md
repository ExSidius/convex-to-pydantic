# Development Guide

## Release Workflow

Releases are **fully automated**. When a PR is merged to `main`, GitHub Actions analyzes
commits since the last release and, if any releasable commits are present, creates a version
tag, publishes to PyPI, and creates a GitHub Release.

**Never create git tags manually.** Tags are managed by the release workflow.

## PR Title Format

This repo uses **squash merges**. The PR title becomes the single commit that lands on
`main`, so **the PR title must follow conventional commits format** — that is what the
release workflow reads to decide whether and how to bump the version.

```
<type>(<optional scope>): <short description>
```

### Types and version impact

| Type | Version bump | When to use |
|------|-------------|-------------|
| `feat:` | minor (`0.x.0`) | New user-facing feature or capability |
| `fix:` | patch (`0.0.x`) | Bug fix |
| `feat!:` / `fix!:` | major (`x.0.0`) | Breaking change (also add `BREAKING CHANGE:` in footer) |
| `chore:` | none | Maintenance, dependency updates |
| `docs:` | none | Documentation only |
| `refactor:` | none | Internal refactor, no behavior change |
| `test:` | none | Test changes only |
| `ci:` | none | CI/CD changes |

### Examples

```
feat: add --watch flag to regenerate on schema changes
fix: handle tables with no fields in codegen
feat!: rename --output flag to --out
chore: bump pydantic to 2.7
```

PRs with `feat:` or `fix:` titles trigger a release on merge. PRs with `chore:`,
`docs:`, `ci:`, etc. merge silently without a release.
