# Copyright (c) 2026, Balaji B and contributors
# For license information, please see license.txt

import frappe

from reno_order.integrations.twilio import send_sms

TEMPLATES = {
	"order_confirmed": (
		"Hi {customer}, your renovation order {name} has been confirmed. "
		"Expected installation on {installation_date}. Grand total: {currency}{grand_total}."
	),
	"order_installed": (
		"Hi {customer}, your renovation order {name} has been installed successfully. "
		"Thank you for choosing us."
	),
}


def _get_customer_phone(reno_order_doc):
	if reno_order_doc.contact_person:
		mobile = frappe.db.get_value("Contact", reno_order_doc.contact_person, "mobile_no")
		if mobile:
			return mobile

	customer_name = reno_order_doc.customer
	if not customer_name:
		return None

	primary_contact = frappe.db.get_value("Customer", customer_name, "customer_primary_contact")
	if primary_contact:
		mobile = frappe.db.get_value("Contact", primary_contact, "mobile_no")
		if mobile:
			return mobile

	return frappe.db.get_value("Customer", customer_name, "mobile_no")


def _should_notify(settings, trigger_event):
	if not settings.enabled:
		return False
	if trigger_event == "order_confirmed" and not settings.notify_on_confirmed:
		return False
	if trigger_event == "order_installed" and not settings.notify_on_installed:
		return False
	return True


def _render_body(trigger_event, reno_order_doc):
	template = TEMPLATES.get(trigger_event)
	if not template:
		return None

	currency_symbol = frappe.db.get_value("Company", frappe.defaults.get_global_default("company"), "default_currency") or ""

	return template.format(
		customer=reno_order_doc.customer,
		name=reno_order_doc.name,
		installation_date=frappe.format(reno_order_doc.expected_installation_date, "Date"),
		grand_total=frappe.utils.fmt_money(reno_order_doc.grand_total),
		currency=f"{currency_symbol} " if currency_symbol else "",
	)


def enqueue_customer_notification(reno_order_name, trigger_event):
	job_id = f"reno-twilio-{trigger_event}-{reno_order_name}"
	frappe.enqueue(
		"reno_order.integrations.notifications.dispatch_customer_notification",
		queue="short",
		job_id=job_id,
		job_name=job_id,
		deduplicate=True,
		enqueue_after_commit=True,
		reno_order_name=reno_order_name,
		trigger_event=trigger_event,
	)


def dispatch_customer_notification(reno_order_name, trigger_event):
	doc = frappe.get_doc("Reno Order", reno_order_name)

	settings = frappe.get_cached_doc("Twilio Settings")
	if not _should_notify(settings, trigger_event):
		return

	phone = _get_customer_phone(doc)
	if not phone:
		frappe.logger("reno_order.twilio").info(
			f"Skipping Twilio notification for {reno_order_name}: no customer phone number on file."
		)
		return

	body = _render_body(trigger_event, doc)
	if not body:
		return

	send_sms(reno_order_name, phone, body, trigger_event=trigger_event)
