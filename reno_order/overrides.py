# Copyright (c) 2026, Balaji B and contributors
# For license information, please see license.txt

import frappe


def propagate_to_delivery_note(doc, method=None):
	if doc.get("reno_order") or not doc.get("items"):
		return

	for item in doc.items:
		so = item.get("against_sales_order")
		if not so:
			continue
		reno_order = frappe.db.get_value("Sales Order", so, "reno_order")
		if reno_order:
			doc.reno_order = reno_order
			break

	if not doc.get("reno_order"):
		return

	for item in doc.items:
		if not item.get("reno_order"):
			item.reno_order = doc.reno_order


def propagate_to_sales_invoice(doc, method=None):
	if doc.get("reno_order") or not doc.get("items"):
		return

	for item in doc.items:
		reno_order = None
		if item.get("sales_order"):
			reno_order = frappe.db.get_value("Sales Order", item.sales_order, "reno_order")
		if not reno_order and item.get("delivery_note"):
			reno_order = frappe.db.get_value("Delivery Note", item.delivery_note, "reno_order")

		if reno_order:
			doc.reno_order = reno_order
			break

	if not doc.get("reno_order"):
		return

	for item in doc.items:
		if not item.get("reno_order"):
			item.reno_order = doc.reno_order
