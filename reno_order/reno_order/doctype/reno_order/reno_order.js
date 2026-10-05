// Copyright (c) 2026, Balaji B and contributors
// For license information, please see license.txt

frappe.ui.form.on("Reno Order", {
	setup(frm) {
		frm.set_query("customer_address", () => ({
			query: "frappe.contacts.doctype.address.address.address_query",
			filters: {
				link_doctype: "Customer",
				link_name: frm.doc.customer,
			},
		}));

		frm.set_query("contact_person", () => ({
			query: "frappe.contacts.doctype.contact.contact.contact_query",
			filters: {
				link_doctype: "Customer",
				link_name: frm.doc.customer,
			},
		}));
	},

	refresh(frm) {
		frm.trigger("setup_sales_order_button");
		frm.trigger("setup_mark_installed_button");
		frm.trigger("toggle_installation_section");
	},

	customer(frm) {
		if (!frm.doc.customer) {
			frm.set_value("customer_address", null);
			frm.set_value("contact_person", null);
		}
	},

	expected_installation_date(frm) {
		if (!frm.doc.transaction_date || !frm.doc.expected_installation_date) return;

		if (
			frappe.datetime.str_to_obj(frm.doc.expected_installation_date) <
			frappe.datetime.str_to_obj(frm.doc.transaction_date)
		) {
			frappe.msgprint({
				title: __("Invalid Installation Date"),
				message: __(
					"Expected Installation Date cannot be earlier than the Transaction Date ({0}).",
					[frappe.datetime.str_to_user(frm.doc.transaction_date)],
				),
				indicator: "red",
			});
			frm.set_value("expected_installation_date", null);
		}
	},

	setup_sales_order_button(frm) {
		if (frm.doc.docstatus !== 1) return;
		if (frm.doc.status !== "Confirmed") return;
		if (frm.doc.sales_order) return;

		frm.add_custom_button(
			__("Sales Order"),
			() => {
				frappe.model.open_mapped_doc({
					method: "reno_order.reno_order.doctype.reno_order.reno_order.make_sales_order",
					frm: frm,
				});
			},
			__("Create"),
		);
		frm.page.set_inner_btn_group_as_primary(__("Create"));
	},

	setup_mark_installed_button(frm) {
		if (frm.doc.docstatus !== 1) return;
		if (frm.doc.status !== "Ready for Installation") return;
		if (!frappe.user.has_role("Site Supervisor") && !frappe.user.has_role("System Manager"))
			return;

		frm
			.add_custom_button(__("Mark as Installed"), () => {
				frappe.confirm(
					__("Mark {0} as Installed? The customer will be notified by SMS.", [frm.doc.name]),
					() => frm.events.call_mark_installed(frm),
				);
			})
			.addClass("btn-primary");
	},

	call_mark_installed(frm) {
		frappe.call({
			method: "reno_order.api.update_installation_status",
			args: {
				reno_order: frm.doc.name,
				status: "Installed",
			},
			freeze: true,
			freeze_message: __("Marking as Installed..."),
			callback: (r) => {
				if (!r.exc) {
					frappe.show_alert({
						message: __("Status updated to Installed."),
						indicator: "green",
					});
					frm.reload_doc();
				}
			},
		});
	},

	toggle_installation_section(frm) {
		const install_phase_statuses = ["Ready for Installation", "Installed", "Closed"];
		const show = install_phase_statuses.includes(frm.doc.status);
		frm.toggle_display("section_break_installation", show);
		frm.toggle_display("installation_logs", show);
	},

	discount_percentage(frm) {
		frm.trigger("recalculate_totals");
	},

	recalculate_totals(frm) {
		let total = 0;
		(frm.doc.order_items || []).forEach((row) => {
			const amount = flt(row.quantity) * flt(row.rate);
			frappe.model.set_value(row.doctype, row.name, "amount", amount);
			total += amount;
		});

		const discount_pct = flt(frm.doc.discount_percentage);
		const discount_amount = flt((total * discount_pct) / 100);

		frm.set_value("total_amount", total);
		frm.set_value("discount_amount", discount_amount);
		frm.set_value("grand_total", total - discount_amount);
	},
});

frappe.ui.form.on("Order Items", {
	quantity(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (flt(row.quantity) <= 0) {
			frappe.show_alert({
				message: __("Row #{0}: Quantity must be greater than zero.", [row.idx]),
				indicator: "orange",
			});
		}
		frm.trigger("recalculate_totals");
	},

	rate(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (flt(row.rate) < 0) {
			frappe.show_alert({
				message: __("Row #{0}: Rate cannot be negative.", [row.idx]),
				indicator: "orange",
			});
		}
		frm.trigger("recalculate_totals");
	},

	order_items_remove(frm) {
		frm.trigger("recalculate_totals");
	},
});
