## Agent skills

### Issue tracker

Issues and specs are tracked in GitHub Issues using the `gh` CLI. See `docs/agents/issue-tracker.md`.

### GitHub network operations

The desktop workspace sandbox cannot reach `api.github.com`. Run GitHub API operations (`gh`) and remote GitHub Git operations (`git fetch`, `git pull`, `git push`) with elevated permissions from the outset. Keep local-only Git operations sandboxed. Do not treat a sandboxed connection failure as invalid GitHub authentication; verify `gh auth status` outside the sandbox first.

### Domain docs

This repo uses single-context domain documentation. See `docs/agents/domain.md`.
