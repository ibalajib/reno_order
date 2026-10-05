from frappe import _


def get_data():
	return {
		"fieldname": "reno_order",
		"transactions": [
			{
				"label": _("Selling"),
				"items": ["Sales Order", "Delivery Note", "Sales Invoice"],
			}
		],
	}
