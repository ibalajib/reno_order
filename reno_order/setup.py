# Copyright (c) 2026, Balaji B and contributors
# For license information, please see license.txt

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def create_reno_order_custom_fields():
	link_field = {
		"fieldname": "reno_order",
		"label": "Reno Order",
		"fieldtype": "Link",
		"options": "Reno Order",
		"insert_after": "project",
		"read_only": 1,
		"no_copy": 1,
		"print_hide": 1,
	}

	custom_fields = {
		"Sales Order": [link_field],
		"Sales Order Item": [link_field],
		"Delivery Note": [link_field],
		"Delivery Note Item": [link_field],
		"Sales Invoice": [link_field],
		"Sales Invoice Item": [link_field],
	}
	create_custom_fields(custom_fields, ignore_validate=True)
