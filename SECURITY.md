# Security

## Model

dpcli is installed into projects as a git submodule and updates itself on session start (`dpcli update --auto`). Pull requests to this repository are reviewed and merged by an AI reviewer in CI. That makes the central repository a supply-chain point for every project using it, so:

- clients update only to tags `vN` created by CI after a merge, never to branches or open PRs;
- the AI reviewer runs on `pull_request_target` without checking out or executing PR code, and treats instructions inside a PR as data;
- tests run on `pull_request` without secrets, so PRs from forks cannot read them;
- changes to `.github/workflows/` cannot be merged by the CI token and always need a maintainer;
- the AI review runs for every author, including those without write access (`allowed_non_write_users`); it can only read the PR and comment, and only the reviewer bot's own `VERDICT:` comment is acted on;
- a project can freeze its version: `dpcli update --pin vN`; a bad release is reverted by a regular revert PR.

## Reporting a vulnerability

Do not open a public issue. Use GitHub's private vulnerability reporting (*Security → Report a vulnerability*) on this repository. Expect a first answer within a few days.
