# Copyright (c) 2026, Balaji B and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.mapper import get_mapped_doc
from frappe.utils import flt, getdate

from reno_order.integrations.notifications import enqueue_customer_notification

STATUS_EVENT_MAP = {
	"Confirmed": "order_confirmed",
	"Installed": "order_installed",
}


class RenoOrder(Document):
	def validate(self):
		self.validate_dates()
		self.validate_items()
		self.calculate_totals()
		self.validate_discount_approval()

	def before_submit(self):
		if self.status == "Draft":
			self.status = "Confirmed"

	def on_submit(self):
		self._trigger_status_notification(previous_status=None)

	def on_update_after_submit(self):
		previous_status = (self.get_doc_before_save() or {}).get("status") if self.get_doc_before_save() else None
		self._trigger_status_notification(previous_status=previous_status)

	def on_cancel(self):
		self.status = "Cancelled"
		self.db_set("status", "Cancelled")

	def _trigger_status_notification(self, previous_status):
		event = STATUS_EVENT_MAP.get(self.status)
		if not event:
			return
		if previous_status == self.status:
			return
		enqueue_customer_notification(self.name, event)

	def validate_dates(self):
		if not self.transaction_date or not self.expected_installation_date:
			return

		if getdate(self.expected_installation_date) < getdate(self.transaction_date):
			frappe.throw("Expected Installation Date ({0}) cannot be before Transaction Date ({1}).").format(frappe.format(self.expected_installation_date, "Date"),frappe.format(self.transaction_date, "Date"))


	def validate_items(self):
		if not self.order_items:
			frappe.throw(_("At least one row is required in Order Items."))

		for row in self.order_items:
			if flt(row.quantity) <= 0:
				frappe.throw("Row #{0}: Quantity must be greater than zero.").format(row.idx)

			if flt(row.rate) < 0:
				frappe.throw("Row #{0}: Rate cannot be negative.").format(row.idx)

	def calculate_totals(self):
		total = 0.0

		for row in self.order_items:
			row.amount = flt(flt(row.quantity) * flt(row.rate), row.precision("amount"))
			total += row.amount

		self.total_amount = flt(total, self.precision("total_amount"))

		discount_pct = flt(self.discount_percentage)
		if discount_pct < 0 or discount_pct > 100:
			frappe.throw(_("Discount % must be between 0 and 100."))

		self.discount_amount = flt(
			self.total_amount * discount_pct / 100.0, self.precision("discount_amount")
		)
		self.grand_total = flt(
			self.total_amount - self.discount_amount, self.precision("grand_total")
		)

	def validate_discount_approval(self):
		if self.docstatus != 1:
			return

		settings = frappe.get_cached_doc("Reno Order Settings")
		threshold = flt(settings.discount_approval_threshold)
		approval_role = settings.discount_approval_role

		if flt(self.discount_percentage) <= threshold:
			return

		user_roles = set(frappe.get_roles(frappe.session.user))
		if approval_role and approval_role in user_roles:
			return

		frappe.throw(
			_("Discount of {0}% exceeds the approval threshold of {1}%. Only users with the '{2}' role can submit this order.").format(
				flt(self.discount_percentage),
				threshold,
				approval_role or _("approver"),
			),
			title=_("Discount Approval Required"),
		)


@frappe.whitelist()
def make_sales_order(source_name, target_doc=None):
	existing = frappe.db.get_value("Sales Order",{"reno_order": source_name, "docstatus": ["<", 2]},"name")
	if existing:
		frappe.throw("Sales Order {0} already exists for this Reno Order.").format(frappe.utils.get_link_to_form("Sales Order", existing),title=_("Duplicate Sales Order"))

	source = frappe.get_doc("Reno Order", source_name)
	if source.docstatus != 1:
		frappe.throw(_("Reno Order must be submitted before creating a Sales Order."))

	if source.status != "Confirmed":
		frappe.throw(
			_("Sales Order can only be created when Reno Order status is 'Confirmed'. Current status: {0}.").format(source.status)
		)

	def set_missing_values(source, target):
		target.reno_order = source.name
		target.delivery_date = source.expected_installation_date
		target.order_type = "Sales"
		target.apply_discount_on = "Grand Total"
		target.additional_discount_percentage = flt(source.discount_percentage)
		target.run_method("set_missing_values")
		target.run_method("calculate_taxes_and_totals")

	def update_item(source_row, target_row, source_parent):
		target_row.qty = source_row.quantity
		target_row.rate = source_row.rate
		target_row.delivery_date = source_parent.expected_installation_date
		target_row.warehouse = source_row.warehouse

	target_doc = get_mapped_doc(
		"Reno Order",
		source_name,
		{
			"Reno Order": {
				"doctype": "Sales Order",
				"field_map": {
					"name": "reno_order",
					"transaction_date": "transaction_date",
					"customer": "customer",
					"customer_address": "customer_address",
					"contact_person": "contact_person",
					"project": "project",
				},
				"validation": {"docstatus": ["=", 1]},
			},
			"Order Items": {
				"doctype": "Sales Order Item",
				"field_map": {
					"item": "item_code",
					"description": "description",
					"quantity": "qty",
					"uom": "uom",
					"rate": "rate",
					"warehouse": "warehouse",
				},
				"postprocess": update_item,
			},
		},
		target_doc,
		set_missing_values,
	)

	return target_doc
