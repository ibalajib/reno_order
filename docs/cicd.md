# CI/CD

This document covers Part 17 of the technical assignment — the automated
build/test pipeline, promotion strategy across environments, and rollback
behaviour on a failed production deployment.

## Pipeline overview

Two GitHub Actions workflows live in [`.github/workflows/`](../.github/workflows):

| Workflow | File | Trigger | Purpose |
|---|---|---|---|
| CI | `ci.yml` | Push to `develop` / `main`, every PR | Boots Redis + MariaDB, installs Frappe + ERPNext + Reno Order, runs the test suite. |
| Linters | `linter.yml` | Every PR | `pre-commit` (ruff, eslint, prettier, pyupgrade), Frappe Semgrep rules, `pip-audit` dependency vulnerability scan. |

### Code Push → Build / Setup → Test → Result

```
┌───────────────┐   ┌───────────────────────┐   ┌─────────────────┐   ┌──────────┐
│ git push      │ → │ GitHub Actions boots: │ → │ bench run-tests │ → │ Green ✓  │
│ or open PR    │   │ - Python 3.10         │   │ --app reno_order│   │ or       │
│               │   │ - Node 18             │   │                 │   │ Red ✗    │
│               │   │ - MariaDB 10.6        │   │                 │   │          │
│               │   │ - Redis cache + queue │   │                 │   │          │
│               │   │ - Frappe + ERPNext    │   │                 │   │          │
│               │   │ - Reno Order (editable│   │                 │   │          │
│               │   │   install)            │   │                 │   │          │
└───────────────┘   └───────────────────────┘   └─────────────────┘   └──────────┘
```

The CI service containers (MariaDB, two Redis instances) mirror a real Frappe
runtime so the tests exercise the same code paths as production.

## Branch model

```
feature/*  →  develop  →  main  →  (tag) v<x.y.z>
```

- `feature/<ticket>` branches off `develop`. Open a PR into `develop`.
- `develop` is the integration branch. CI must be green before merge.
- `main` holds release-ready code only. Promotion from `develop` is a
  fast-forward merge after staging validation.
- Every production release is a tag on `main`, named `v<x.y.z>`
  (semver per `CHANGELOG.md`).

## Promotion — Development → Staging → Production

### 1. Development
- Developer branches off `develop`, pushes commits.
- CI runs on push and on PR open; Linters workflow runs on PR.
- PR merged into `develop` only after:
  - CI green on the PR branch.
  - At least one review approval.
  - All review threads resolved.

### 2. Staging
- Staging is a dedicated bench + site that tracks the `develop` branch.
- Deployment is automated by a scheduled action (or `bench update`
  equivalent on the staging host) that pulls the latest `develop`, runs
  `bench migrate`, restarts workers, and smoke-tests the critical paths
  (create Reno Order → submit → create Sales Order via the whitelisted
  method).
- Business users validate on staging. Bugs feed back to new `feature/*`
  branches.

### 3. Production
Promotion is deliberate, not automatic:

1. Open PR `develop → main` with a title that references the sprint /
   release.
2. CI runs on the PR against `main`.
3. On approval + green CI, merge is a **fast-forward merge** (no squash,
   so commit history maps 1:1 to `develop`).
4. Tag the merge commit on `main`:
   ```bash
   git checkout main && git pull
   git tag -a v1.2.0 -m "Release v1.2.0 — Twilio integration + mobile API"
   git push origin v1.2.0
   ```
5. The production host pulls the tag, not the branch:
   ```bash
   bench get-app https://github.com/<org>/reno_order --branch v1.2.0
   bench --site production.local migrate
   bench --site production.local clear-cache
   bench restart
   ```
6. Smoke-test the critical paths. Monitor Error Log and `logs/web.error.log`
   for the first 15 minutes.

## Rollback strategy

Production deployments can fail three different ways. Each has its own
rollback path.

### Case A — Code / app-level failure after `bench update`

Example: new release broke an endpoint, nothing in MariaDB has changed
yet.

```bash
# On the production host
cd $PATH_TO_YOUR_BENCH/apps/reno_order
git checkout <previous-tag>   # e.g. v1.1.0
bench build --app reno_order
bench restart
```

**Recovery time:** seconds. Previous Gunicorn processes keep serving while
the new app files swap in; Supervisor restarts workers.

### Case B — Migration ran but is misbehaving

Example: a patch backfilled the wrong default on `order_type`.

1. **Stop writes first** — enable maintenance mode:
   ```bash
   bench --site production.local set-maintenance-mode on
   ```
2. Restore from the pre-deploy backup (we take one before every migration
   via `bench --site production.local backup --with-files` triggered by
   the deployment script):
   ```bash
   bench --site production.local restore \
     <pre-deploy-sql-dump> \
     --with-public-files <public.tar> \
     --with-private-files <private.tar>
   ```
3. Check out the previous tag, migrate forward from the restored baseline
   (should be a no-op since schema matches), restart.
4. Disable maintenance mode.

**Recovery time:** 5-30 minutes depending on DB size.

### Case C — Partial failure (migration half-applied, DB in inconsistent state)

Worst case. Same as Case B but may need manual data reconciliation after
restore. This is why **pre-deployment backups are mandatory** and the
deployment script must `exit 1` if the backup step fails.

### Prevention — reduce rollback risk

- Every patch is idempotent and chunked (`frappe.db.commit()` every 1000
  rows) so a mid-run failure doesn't lock the DB.
- Patches run inside `bench migrate`, which Frappe wraps in savepoints
  where possible.
- Staging must receive the same migration against a recent production
  backup before promotion.
- A canary rollout — point one worker / one site to the new tag before
  the rest — catches most issues before full promotion. Frappe doesn't
  natively support this; a reverse proxy weight shift is the usual pattern.

## Secrets handling in CI

- No credentials live in the repo. Twilio keys, DB passwords, and site
  configs are supplied at runtime per environment.
- CI uses throwaway services (Redis, MariaDB with `root:root`) spun up as
  GitHub-managed containers; nothing persists beyond the job.
- For staging / production deployments, deployment-key secrets
  (`PROD_DEPLOY_KEY`, `STAGING_SSH_KEY`) are stored in GitHub repository
  secrets and injected into deploy workflows only, never into test jobs.

## Extending this pipeline

If the team grows, obvious next steps:

- Add a `bench build --app reno_order` step to CI so JS/CSS build errors
  are caught early.
- Add coverage reporting with `coverage.py` + `coveralls` action.
- Add a scheduled workflow that runs the suite nightly against the latest
  Frappe `develop` so we catch upstream breakages early.
- Replace the staging-pull cron with a `workflow_dispatch` that only a
  release manager can trigger.
