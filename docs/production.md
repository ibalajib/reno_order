# Production & Server Knowledge

This document covers Part 18 of the technical assignment — Frappe Cloud
operations, the role of each component in a self-hosted ERPNext deployment,
and a quick-reference troubleshooting matrix.

## Frappe Cloud

### Application deployment
- Apps are added through the Frappe Cloud dashboard — pick the Git branch,
  Cloud builds a release group image, and each site in the group migrates
  to that image on the next deploy.
- Deploys are atomic: a new image is built, tested, and only then does
  traffic switch over. Rollback is a one-click revert to the previous
  release.
- Private apps are added by granting Frappe Cloud read access to the
  GitHub repository.

### Backups
- Automatic daily backups are included for every site. Retention depends
  on the plan.
- Manual backups can be triggered from the site dashboard before risky
  migrations.
- Backups include the database, public files, and private files, and can
  be downloaded or restored to another site in-platform.

### Logs
- The site dashboard exposes `web`, `worker`, `scheduler`, and `database`
  slow-query logs with search and tail.
- Error Log (the DocType) is live inside each site, same as self-hosted.
- Long-term log aggregation is handled by Frappe Cloud's own observability
  stack — no need to run ELK/Loki.

### Scheduler and workers
- Workers and the scheduler are managed by Frappe Cloud. The dashboard
  shows worker counts per queue, lets you scale them, and surfaces queue
  depth and failure rates.
- There is no need to SSH in and run `bench start` — the platform owns
  process lifecycle.

### Site configuration
- `site_config.json` values are set from the dashboard under Site Config.
- Encrypted keys and the Twilio Auth Token (stored in `tabAuth`) are
  encrypted using the site's `encryption_key`, which Frappe Cloud manages
  — rotating it is a destructive action, not a routine one.
- Custom domain, SSL (Let's Encrypt), and HTTP → HTTPS redirects are all
  configured per-site from the dashboard.

## Self-hosted ERPNext — role of each component

A typical self-hosted stack:

```
      HTTPS
        │
     ┌──┴──┐
     │Nginx│  (TLS termination, static files, reverse proxy)
     └──┬──┘
        │
   ┌────┴────┐
   │ Gunicorn│  (Python WSGI server running Frappe web workers)
   └────┬────┘
        │
   ┌────┴─────────────────────────┐
   │ Frappe app (python)          │
   └────┬─────────────────────────┘
        │
   ┌────┴──┐    ┌─────────────┐    ┌──────────────┐
   │MariaDB│    │  Redis x2   │    │ RQ Workers   │
   │       │    │ cache/queue │    │ short/default│
   └───────┘    └─────────────┘    │ /long + sched│
                                   └──────────────┘

All processes are supervised by Supervisor (or systemd).
```

### Nginx
- Terminates TLS, serves static files directly from `sites/assets/`, and
  reverse-proxies dynamic requests to Gunicorn.
- Enforces client body size limits, gzip compression, and sensible
  timeouts.
- Routes `/socket.io` to the Node realtime process (not Gunicorn).

### Gunicorn
- Python WSGI server, usually 2 × CPU + 1 workers.
- Each worker handles one HTTP request at a time, synchronously.
- Request timeout is configurable (`--timeout`); long requests that
  exceed it get killed, which is why heavy work must go through the RQ
  queues.

### Supervisor (or systemd)
- Keeps `gunicorn`, `node realtime`, `scheduler`, and the RQ worker
  processes running.
- Restarts them on crash, on `bench restart`, and on deploy.
- `supervisorctl status` is the first command on any ops ticket.

### Redis
- Two instances: `redis_cache` and `redis_queue`.
- `redis_cache` holds short-lived app cache (document cache, session,
  rate limits).
- `redis_queue` is the broker for RQ background jobs.
- Both are configured through `config/redis_cache.conf` and
  `config/redis_queue.conf`; worker counts and max-memory policy live
  there.

### MariaDB
- Primary data store. One schema per site (`_` + site hash).
- Innodb engine, row-level locking.
- Site passwords live in `sites/<site>/site_config.json`.
- Slow query log is critical for performance work — enable it with
  `long_query_time = 1` and tail from `logs/database.log`.

### Workers
- RQ consumers that drain jobs enqueued by `frappe.enqueue(...)`.
- Three default queues: `short` (5 min timeout), `default` (300 s),
  `long` (1500 s). Our Twilio integration uses `short`.
- Scale horizontally by adding more worker processes under Supervisor.

### Scheduler
- A single process that triggers the hourly / daily / weekly / monthly
  / cron jobs declared in each app's `hooks.py`.
- Also fires cleanup, auto-cancellation, email digests, etc.
- If the scheduler stops, enqueued jobs still run (that's the workers'
  job) but *scheduled* work stops immediately.

## Troubleshooting

Fast-reference matrix — first commands to run per symptom.

### 502 Bad Gateway
- Nginx can reach itself but Gunicorn is dead or restarting.
- Check Supervisor: `sudo supervisorctl status frappe:frappe-bench-frappe-web`.
- Tail `logs/web.error.log` for Python traceback or `WORKER TIMEOUT`.
- If Gunicorn is OOM-killed, raise instance size or reduce
  `gunicorn_workers`.
- Restart: `bench restart` (or `sudo supervisorctl restart frappe:`).

### Worker queue backlog
- Check RQ dashboard at `/app/rq-job` or `bench --site <site>
  show-pending-jobs`.
- Confirm workers are alive: `supervisorctl status frappe:*worker*`.
- If workers are running but queue grows → bottleneck is downstream (slow
  external API, DB locks). Profile a single job in isolation.
- Scale workers temporarily: add more `*worker-short*` entries to
  `config/supervisor.conf` and `supervisorctl reread && update`.

### Scheduler not running
- `bench --site <site> doctor` reports scheduler state.
- Check `logs/scheduler.log`.
- Common cause: `scheduler_disabled = 1` in `site_config.json` — toggle
  with `bench --site <site> enable-scheduler`.
- Make sure Supervisor's scheduler process is in `RUNNING` state.

### High CPU usage
- `top -c` — which process? Gunicorn, worker, MariaDB, or Node realtime?
- MariaDB high CPU → run `SHOW PROCESSLIST;`, look for long queries, add
  missing indexes or kill runaway queries.
- Worker high CPU → inspect the job (`frappe.local.job`) in bench
  console; usually an unbounded loop or large query without `limit`.
- Gunicorn high CPU → likely a bad view / endpoint; add profiling
  middleware or `frappe.cache().get_stats()`.

### Slow MariaDB queries
- Enable slow query log in `/etc/mysql/my.cnf`:
  ```
  slow_query_log = 1
  slow_query_log_file = /var/log/mysql/slow.log
  long_query_time = 1
  ```
- Reload: `sudo systemctl reload mariadb`.
- Analyse with `pt-query-digest` or `mysqldumpslow`.
- For a specific slow endpoint, run `EXPLAIN` on the query, add a
  covering index, re-run `EXPLAIN` — should show `type: ref` instead of
  `ALL`.

### Disk full
- `df -h` → which mount?
- Common offenders: `logs/*`, `sites/*/private/backups/*`, orphan
  `*.sql.gz` from aborted backups.
- Rotate logs: `bench rotate-logs` or configure `logrotate` entry.
- Purge old backups: `find sites/*/private/backups -mtime +30 -delete`.
- MariaDB binlogs can balloon — `PURGE BINARY LOGS BEFORE <date>;` if
  binlogs aren't needed for replication.

### Failed migration
1. Check the traceback — printed by `bench migrate` and also in
   `logs/web.error.log` for the live site.
2. If the failure is in a patch, the migration halted — DB may be in a
   partial state. **Do not run migrate again blindly.**
3. Identify the failed patch from the traceback, mark the previous patch
   as the last successful one in `tabPatch Log`, fix the patch code (or
   data), redeploy.
4. If data is corrupted, restore from the pre-deployment backup (see
   [cicd.md](cicd.md) rollback section).
5. In all cases, after recovery run `bench --site <site> doctor` to
   confirm schema and app state are consistent.

## Operational habits

- Every production change goes through a tagged release — never a
  branch tip.
- Backups verified by occasional test-restores on staging, not just
  "backup succeeded" alerts.
- Alerts on `logs/web.error.log` lines matching `WORKER TIMEOUT`,
  `OperationalError`, `MySQLdb._exceptions.OperationalError`.
- Dashboards for queue depth per RQ queue, request latency per endpoint,
  MariaDB connections.
- Scheduled drill: once a quarter, restore the latest production backup
  on a scratch site and verify key reports and totals match.
