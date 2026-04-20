# Development Guide

## Release Workflow

Releases are **fully automated**. When a PR is merged to `main`, GitHub Actions analyzes
commits since the last release and, if any releasable commits are present, creates a version
tag, publishes to PyPI, and creates a GitHub Release.

**Never create git tags manually.** Tags are managed by the release workflow.

## Commit Message Format

This project uses [Conventional Commits](https://www.conventionalcommits.org/) to determine
version bumps automatically.

```
<type>(<optional scope>): <short description>

[optional body]

[optional footer]
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

BREAKING CHANGE: --output has been renamed to --out
chore: bump pydantic to 2.7
```

Every PR with user-facing changes should include at least one `feat:` or `fix:` commit.
PRs with only `chore:`, `docs:`, etc. will merge without triggering a release.
