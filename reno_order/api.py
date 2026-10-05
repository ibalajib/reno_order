# Copyright (c) 2026, Balaji B and contributors
# For license information, please see license.txt

import base64
import binascii

import frappe
from frappe import _
from frappe.model.workflow import apply_workflow
from frappe.utils import now_datetime

SUPERVISOR_ROLE = "Site Supervisor"
INSTALLATION_PHASE_STATUSES = ("Ready for Installation", "Installed")
ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "heic"}
MAX_PHOTO_SIZE_MB = 10


def _require_authenticated():
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required."), frappe.AuthenticationError)


def _require_supervisor_role():
	if SUPERVISOR_ROLE not in frappe.get_roles(frappe.session.user):
		frappe.throw(
			_("Only users with the '{0}' role can perform this action.").format(SUPERVISOR_ROLE),
			frappe.PermissionError,
		)


def _get_reno_order(name):
	if not name:
		frappe.throw(_("Field 'reno_order' is required."))

	if not frappe.db.exists("Reno Order", name):
		frappe.throw(_("Reno Order {0} not found.").format(name), frappe.DoesNotExistError)

	doc = frappe.get_doc("Reno Order", name)
	doc.check_permission("read")
	return doc


@frappe.whitelist(methods=["POST"])
def update_installation_status(reno_order, status):
	_require_authenticated()
	_require_supervisor_role()

	doc = _get_reno_order(reno_order)

	if doc.docstatus != 1:
		frappe.throw(_("Reno Order must be submitted."))

	if status != "Installed":
		frappe.throw(
			_("This endpoint can only transition status to 'Installed'. Received: {0}.").format(status)
		)

	if doc.status != "Ready for Installation":
		frappe.throw(
			_("Status can only move to 'Installed' from 'Ready for Installation'. Current status: {0}.").format(
				doc.status
			)
		)

	apply_workflow(doc, "Mark Installed")

	return {
		"ok": True,
		"reno_order": doc.name,
		"status": doc.status,
	}


@frappe.whitelist(methods=["POST"])
def add_installation_remarks(reno_order, remarks):
	_require_authenticated()
	_require_supervisor_role()

	remarks = (remarks or "").strip()
	if not remarks:
		frappe.throw(_("Field 'remarks' cannot be empty."))

	doc = _get_reno_order(reno_order)

	if doc.docstatus != 1:
		frappe.throw(_("Reno Order must be submitted before adding installation remarks."))

	if doc.status not in INSTALLATION_PHASE_STATUSES:
		frappe.throw(
			_("Remarks can only be added when status is 'Ready for Installation' or 'Installed'. Current: {0}.").format(
				doc.status
			)
		)

	doc.append(
		"installation_logs",
		{
			"posted_on": now_datetime(),
			"posted_by": frappe.session.user,
			"remarks": remarks,
		},
	)
	doc.save(ignore_permissions=False)

	return {
		"ok": True,
		"reno_order": doc.name,
		"log_count": len(doc.installation_logs),
	}


@frappe.whitelist(methods=["POST"])
def attach_site_photo(reno_order, file_name, file_content, is_private=1):
	_require_authenticated()
	_require_supervisor_role()

	doc = _get_reno_order(reno_order)

	if doc.docstatus != 1:
		frappe.throw(_("Reno Order must be submitted before attaching site photos."))

	if doc.status not in INSTALLATION_PHASE_STATUSES:
		frappe.throw(
			_("Photos can only be attached during the installation phase. Current status: {0}.").format(
				doc.status
			)
		)

	if not file_name or "." not in file_name:
		frappe.throw(_("A valid file_name with extension is required."))

	extension = file_name.rsplit(".", 1)[-1].lower()
	if extension not in ALLOWED_IMAGE_EXTENSIONS:
		frappe.throw(
			_("File type .{0} is not allowed. Allowed types: {1}.").format(
				extension, ", ".join(sorted(ALLOWED_IMAGE_EXTENSIONS))
			)
		)

	try:
		decoded = base64.b64decode(file_content, validate=True)
	except (binascii.Error, ValueError):
		frappe.throw(_("file_content must be a valid base64-encoded string."))

	size_mb = len(decoded) / (1024 * 1024)
	if size_mb > MAX_PHOTO_SIZE_MB:
		frappe.throw(
			_("File size {0:.2f} MB exceeds the limit of {1} MB.").format(size_mb, MAX_PHOTO_SIZE_MB)
		)

	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": file_name,
			"attached_to_doctype": "Reno Order",
			"attached_to_name": doc.name,
			"is_private": 1 if int(is_private or 0) else 0,
			"content": decoded,
		}
	).insert(ignore_permissions=False)

	return {
		"ok": True,
		"reno_order": doc.name,
		"file_url": file_doc.file_url,
		"file_name": file_doc.file_name,
	}
