# Codex issue orchestrator

This repository can turn a deliberately labeled GitHub issue into a Codex implementation branch and pull request without polling.

## How it works

1. A maintainer adds the exact label `agent:codex` to an issue.
2. GitHub emits the `issues:labeled` event and starts `.github/workflows/codex-issue-orchestrator.yml`.
3. The workflow checks out `main` and creates `agent/issue-<number>`.
4. A pinned Codex CLI runs in `workspace-write` mode and receives the issue title/body plus repository safety instructions.
5. The workflow runs the repository unittest suite and `git diff --check`.
6. If Codex produced changes and all checks pass, GitHub Actions commits and pushes the branch and opens a pull request containing `Closes #<number>`.
7. Nothing is merged automatically. A human still reviews and merges the PR.

There is no background polling service and no requirement for the maintainer's computer to stay on.

## One-time setup

### 1. Create the label

Create a repository label named exactly:

`agent:codex`

Only adding this exact label triggers the coding job.

### 2. Configure the OpenAI API key

Create an OpenAI API key for automation and save it as the repository Actions secret:

`OPENAI_API_KEY`

Do not store the key in repository files, issue text, comments, or workflow variables.

The ChatGPT subscription and OpenAI API billing are separate. This workflow uses the API key and therefore consumes API usage.

### 3. Allow GitHub Actions to open pull requests

In the repository Actions settings, ensure the workflow token is allowed to create pull requests. The workflow requests only the GitHub permissions it needs for this job: `contents: write`, `issues: write`, and `pull-requests: write`.

## Usage

Write a normal, well-scoped issue with acceptance criteria and safety boundaries. When it is ready for autonomous implementation, add `agent:codex`.

The expected flow is:

`Issue + agent:codex` → `GitHub event` → `GitHub Actions` → `Codex` → `tests` → `branch` → `PR` → `human merge`

## Safety properties

- No automatic merge.
- No Gmail credentials or mailbox data are provided to Codex by this workflow.
- Codex is told not to push, merge, release, or change GitHub settings; GitHub Actions owns the Git operations after the coding step.
- Codex runs with a workspace-write sandbox, not unrestricted host access.
- Existing remote `agent/issue-<number>` branches are never overwritten.
- Failure of Codex, the test suite, or whitespace validation stops before a PR is created.
- Per-issue concurrency prevents two simultaneous runs for the same issue.

## Current pinned tool

The workflow currently pins `@openai/codex@0.154.0` rather than using a floating latest version. Upgrade this deliberately through a reviewed pull request.