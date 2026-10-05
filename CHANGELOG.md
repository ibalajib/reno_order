# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Automated test suite covering 16 business-critical scenarios (totals, discount
  authorization, validation, Sales Order creation, duplicate prevention, API
  authorization, status processing, patch behaviour).

## [0.6.0] - 2026-10-05

### Added
- **Twilio SMS integration** (`reno_order/integrations/twilio.py`) with
  configurable retries, exponential backoff, request timeout, and error
  classification (retryable vs permanent).
- **Twilio Settings** single DocType with encrypted Auth Token storage
  (`fieldtype: Password`), trial-mode body override, and per-event notification
  toggles.
- **Twilio Message Log** DocType providing a permanent per-attempt audit trail.
- Background job pipeline using `frappe.enqueue` with `job_id` + `deduplicate`
  + `enqueue_after_commit` so slow SMS sends never block the user's save.
- Status-change notification triggers on `Confirmed` and `Installed`.

## [0.5.0] - 2026-10-05

### Added
- Client-side form enhancements:
  - Dynamic query filters on Customer Address and Contact Person.
  - Conditional visibility of Installation section based on status.
  - Custom button "Mark as Installed" visible only to Site Supervisors when
    status is `Ready for Installation`.
  - Friendly inline validation for installation date and item row values.
  - Real-time totals recalculation on quantity, rate, and discount changes.

## [0.4.0] - 2026-10-05

### Added
- REST API endpoints under `reno_order/api.py` for the Site Supervisor mobile
  app:
  - `update_installation_status`
  - `add_installation_remarks`
  - `attach_site_photo`
- `Installation Log` child DocType for appending remarks with timestamp +
  posting user.
- Allowed base64 image upload with file-type and size validation.

### Security
- All endpoints enforce authentication, role check (`Site Supervisor`),
  current-status gate, and allowed-transition validation server-side even
  though the client UI hides the actions.

## [0.3.0] - 2026-10-04

### Added
- ERPNext integration layer:
  - Custom `reno_order` field on Sales Order, Delivery Note, Sales Invoice and
    their item child tables (installed via `after_install` and `after_migrate`
    hooks in `reno_order/setup.py`).
  - Dashboard config exposing a Connections panel on Reno Order showing linked
    Sales Order / Delivery Note / Sales Invoice counts.
  - `before_insert` doc events on Delivery Note and Sales Invoice walk back
    through standard ERPNext item references and populate the `reno_order`
    link automatically.

## [0.2.0] - 2026-10-04

### Added
- Workflow definition (Draft → Confirmed → In Production → Ready for
  Installation → Installed → Closed, with Cancelled branch) mapped to the
  `status` field.
- Role-based "Only Allow Edit For" per state, and self-approval enabled on
  transitions where the actor is the record owner.

## [0.1.0] - 2026-10-04

### Added
- Custom app `reno_order` scaffolded via `bench new-app`.
- `Reno Order` DocType with full header fields, submittable, naming series
  `RO-.YYYY.-`.
- `Order Items` child table with Item, Description, Quantity, UOM, Rate,
  Amount, Warehouse.
- `Reno Order Settings` single DocType holding the discount approval
  threshold and the role authorised to approve.
- Server-side logic:
  - Line-item amount computation and header totals (Total Amount, Discount
    Amount, Grand Total) recomputed on every save so posted values cannot be
    forged through the API.
  - Validation: non-negative quantity and rate, installation date not before
    transaction date, discount percentage in `[0, 100]`.
  - Discount approval gate — submission is blocked when the discount exceeds
    the configured threshold unless the user holds the approval role.
  - `make_sales_order` whitelisted method with duplicate prevention and
    status gate (only `Confirmed` orders).
- Client-side form script with real-time totals and a status-aware
  "Create → Sales Order" button.
