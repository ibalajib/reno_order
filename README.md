# Reno Order

Custom Frappe/ERPNext application for managing the kitchen-renovation
workflow end-to-end — quotation, confirmation, manufacturing, procurement,
installation and invoicing — while keeping standard ERPNext as the system of
record for financials and inventory.

Built for Frappe/ERPNext **v16**.

---

## Table of Contents

1. [Scope & Business Flow](#scope--business-flow)
2. [Architecture Overview](#architecture-overview)
3. [Prerequisites](#prerequisites)
4. [Installation](#installation)
5. [Configuration](#configuration)
6. [Workflow & Roles](#workflow--roles)
7. [REST API](#rest-api)
8. [Testing](#testing)
9. [Assumptions](#assumptions)
10. [Known Limitations](#known-limitations)
11. [Development Notes](#development-notes)
12. [License](#license)

---

## Scope & Business Flow

A single Reno Order represents one kitchen-renovation engagement.

```
Draft → Confirmed → In Production → Ready for Installation → Installed → Closed
                                                                   ↑
                                                     Cancelled (any pre-install)
```

- Draft is the editable quotation stage.
- Confirmed submits the document (`docstatus = 1`) and locks pricing.
- Confirmed is also the point at which a standard ERPNext **Sales Order** is
  generated — the custom app never duplicates ERPNext ledger behaviour.
- Installed triggers downstream fulfilment (Delivery Note, Sales Invoice) and
  an SMS to the customer.

## Architecture Overview

| Layer | Module | Responsibility |
|---|---|---|
| DocTypes | `reno_order/doctype/reno_order` | Header, Order Items child, submittable lifecycle. |
| Settings | `reno_order/doctype/reno_order_settings` | Discount approval threshold + role (single). |
| Settings | `reno_order/doctype/twilio_settings` | Encrypted Twilio credentials + feature toggles (single). |
| Audit | `reno_order/doctype/twilio_message_log` | Immutable row per SMS attempt. |
| Audit | `reno_order/doctype/installation_log` | Child table for site remarks (mobile API). |
| API | `reno_order/api.py` | Whitelisted REST endpoints for the Site Supervisor mobile app. |
| Integrations | `reno_order/integrations/twilio.py` | HTTP client with retry, timeout, error classification. |
| Integrations | `reno_order/integrations/notifications.py` | Business layer — picks phone, renders template, enqueues. |
| Overrides | `reno_order/overrides.py` | `before_insert` doc events to propagate `reno_order` link to Delivery Note / Sales Invoice. |
| Setup | `reno_order/setup.py` | Idempotently creates custom fields on Sales Order / Delivery Note / Sales Invoice (and children) via `after_install` and `after_migrate`. |
| Dashboard | `reno_order/doctype/reno_order/reno_order_dashboard.py` | Sidebar Connections panel. |

Code is split by **responsibility**, not by file size. Each module imports
from the layer below it and never upward.

## Prerequisites

- Frappe/ERPNext **v16** bench installed.
- Python 3.10+ (tested on 3.10).
- Node 18+ (for build assets).
- Redis + MariaDB per standard Frappe setup.
- For the ERPNext demo flow: at least one Company, Customer, Item, Warehouse,
  and opening stock in the warehouse.

## Installation

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app https://github.com/<you>/reno_order --branch main
bench --site <your-site> install-app reno_order
bench --site <your-site> migrate
```

On install the app:

1. Creates custom fields `reno_order` on Sales Order / Delivery Note / Sales
   Invoice (and their item child tables).
2. Registers doc events for back-reference propagation.
3. Seeds default values on `Reno Order Settings` (threshold 10 %, approver
   role `Sales Manager`).

## Configuration

### Discount Approval

Open **Reno Order Settings** and set:

- Discount Approval Threshold — percentage above which submission is blocked.
- Discount Approval Role — role that may submit over-threshold orders.

### Workflow

The workflow definition is created manually in Desk (not shipped as a
fixture to keep review flexibility). Create it with:

- Document Type: `Reno Order`
- Workflow State Field: `status`
- States, roles, and transitions as documented in
  [`docs/workflow.md`](docs/workflow.md) *(if present)* or in Section 2 of the
  assignment submission note.

### Twilio (SMS notifications)

Open **Twilio Settings** and fill:

| Field | Value |
|---|---|
| Enabled | ✓ |
| Account SID | from Twilio console |
| Auth Token | from Twilio console (stored encrypted in `tabAuth`) |
| From Number | your Twilio SMS sender (e.g. `+17372508034`) |
| Default Country Code | e.g. `+91` for Indian numbers |
| Notify Customer on 'Confirmed' | ✓ |
| Notify Customer on 'Installed' | ✓ |
| Request Timeout | `10` seconds |
| Max Retries | `3` |
| Trial Mode | ✓ when on a Twilio trial account |
| Trial Body Override | `sms_appointment_reminders` (default) |

**Trial Mode** sends an approved template keyword as the message body so that
Twilio trial accounts accept the call. The real business message is still
recorded in Twilio Message Log for audit. Toggle off once the Twilio account
is upgraded.

> ⚠️ Never commit real credentials. Everything secret lives in Settings
> DocTypes, which are site-specific and never in Git.

## Workflow & Roles

| Role | Capability |
|---|---|
| Sales User | Create and confirm orders within their own records. |
| Sales Manager | Broader visibility, approves high-discount orders, can cancel. |
| Production User | Moves order through In Production → Ready for Installation. |
| Site Supervisor | Hits the mobile API to mark Installed and attach site photos. |
| Accounts User | Closes the order once invoicing is complete. |

Permission matrix is enforced server-side; client-side scripts hide
actions purely for UX.

## REST API

Base URL: `https://<site>/api/method/reno_order.api.<endpoint>`

Authentication is Frappe's API Key + Secret:

```
Authorization: token <api_key>:<api_secret>
```

| Endpoint | Method | Purpose |
|---|---|---|
| `update_installation_status` | POST | Transition `Ready for Installation` → `Installed` through the workflow. |
| `add_installation_remarks` | POST | Append a timestamped remark to `installation_logs`. |
| `attach_site_photo` | POST | Attach a base64-encoded image (JPEG/PNG/WEBP/HEIC up to 10 MB). |

Every endpoint enforces:

1. Authentication (`frappe.session.user != "Guest"`).
2. Role (`Site Supervisor`).
3. Current status gate.
4. Target-status validation.
5. Document-level `check_permission("read")`.

Example:

```bash
curl -X POST "https://reno.local/api/method/reno_order.api.update_installation_status" \
  -H "Authorization: token $API_KEY:$API_SECRET" \
  -d "reno_order=RO-2026-00001&status=Installed"
```

## Testing

Run the full suite:

```bash
bench --site <your-site> run-tests --app reno_order
```

Or a single module:

```bash
bench --site <your-site> run-tests --module \
  reno_order.reno_order.doctype.reno_order.test_reno_order
```

Covered scenarios (16 tests):

- Total / discount / grand-total calculation and manipulation resistance.
- Invalid installation date, negative quantity, negative rate.
- Discount authorization (role-gated submission).
- Sales Order creation, status gate, and duplicate prevention.
- API authentication, authorization, and status-transition guards.
- Installed-status notification enqueue (mocked — no real SMS).
- `order_type` patch backfill idempotency.

## Assumptions

- Standard ERPNext selling + stock modules handle all financial and
  inventory postings. The custom app does not re-implement them.
- A Reno Order maps 1:1 to one Sales Order (and from there to one or more
  Delivery Notes / Sales Invoices).
- SMS notifications use Twilio. The design is pluggable — swapping the
  provider only requires a new client under `integrations/`.
- Site Supervisors operate exclusively through the mobile API. The Desk UI
  button for "Mark as Installed" is a convenience path for admins.
- Discount approval is single-level. Multi-level approval would require a
  dedicated approvals DocType.

## Known Limitations

- Workflow is created manually in Desk, not shipped as a fixture. Fixturing
  it is a one-liner (`hooks.py` → `fixtures`) and left out to keep review
  diffs small.
- No per-user territory filter on Reno Order (would need
  User Permissions or a `permission_query_conditions` hook — flagged for
  Part 11 of the submission).
- Trial Twilio bodies are canned keywords, not real messages. Production
  accounts send the real body as-is.
- Downstream auto-creation (Delivery Note on Installed) is not wired in this
  version — users create DN/SI through the standard ERPNext buttons on the
  Sales Order. This is a deliberate choice to keep the audit trail obvious
  during the demo.

## Development Notes

- Formatting / linting is managed by `pre-commit` (ruff, eslint, prettier,
  pyupgrade). Install with:
  ```bash
  cd apps/reno_order && pre-commit install
  ```
- CI configuration lives in `.github/workflows/`.
- The `__pycache__` / `*.pyc` / `logs/` / backup paths are ignored by
  `.gitignore` — never commit site data or credentials.

## License

MIT — see `license.txt`.
