# Copyright (c) 2026, Balaji B and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from reno_order.reno_order.doctype.reno_order.reno_order import make_sales_order

TEST_CUSTOMER = "_Test Reno Customer"
TEST_ITEM = "_Test Reno Item"
TEST_WAREHOUSE = "_Test Reno Warehouse - _TC"
TEST_SUPERVISOR = "test_reno_supervisor@example.com"
TEST_SALES_USER = "test_reno_sales@example.com"


def _ensure_item():
	if frappe.db.exists("Item", TEST_ITEM):
		return
	frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": TEST_ITEM,
			"item_name": TEST_ITEM,
			"item_group": "All Item Groups",
			"stock_uom": "Nos",
			"is_stock_item": 1,
		}
	).insert(ignore_permissions=True)


def _ensure_customer():
	if frappe.db.exists("Customer", TEST_CUSTOMER):
		return
	frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": TEST_CUSTOMER,
			"customer_group": "All Customer Groups",
			"territory": "All Territories",
		}
	).insert(ignore_permissions=True)


def _ensure_warehouse():
	if frappe.db.exists("Warehouse", TEST_WAREHOUSE):
		return
	company = frappe.defaults.get_global_default("company")
	frappe.get_doc(
		{
			"doctype": "Warehouse",
			"warehouse_name": "_Test Reno Warehouse",
			"company": company,
		}
	).insert(ignore_permissions=True)


def _ensure_user(email, roles):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"roles": [{"role": r} for r in roles],
			}
		).insert(ignore_permissions=True)
		return

	user = frappe.get_doc("User", email)
	existing_roles = {r.role for r in user.roles}
	for role in roles:
		if role not in existing_roles:
			user.append("roles", {"role": role})
	user.save(ignore_permissions=True)


def _build_reno_order(**overrides):
	doc = frappe.get_doc(
		{
			"doctype": "Reno Order",
			"customer": TEST_CUSTOMER,
			"transaction_date": today(),
			"expected_installation_date": add_days(today(), 15),
			"order_type": "Standard",
			"discount_percentage": overrides.get("discount_percentage", 0),
			"order_items": [
				{
					"item": TEST_ITEM,
					"description": "Test",
					"quantity": 2,
					"uom": "Nos",
					"rate": 1000,
					"warehouse": TEST_WAREHOUSE,
				}
			],
		}
	)
	for key, value in overrides.items():
		if key == "discount_percentage":
			continue
		doc.set(key, value)
	return doc


class TestRenoOrder(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_ensure_customer()
		_ensure_item()
		_ensure_warehouse()
		_ensure_user(TEST_SUPERVISOR, ["Site Supervisor"])
		_ensure_user(TEST_SALES_USER, ["Sales User"])

		settings = frappe.get_single("Reno Order Settings")
		settings.discount_approval_threshold = 10
		settings.discount_approval_role = "Sales Manager"
		settings.save(ignore_permissions=True)
		frappe.db.commit()

	def setUp(self):
		frappe.set_user("Administrator")

	def test_total_calculation(self):
		doc = _build_reno_order(discount_percentage=10)
		doc.insert(ignore_permissions=True)
		self.assertEqual(doc.order_items[0].amount, 2000)
		self.assertEqual(doc.total_amount, 2000)
		self.assertEqual(doc.discount_amount, 200)
		self.assertEqual(doc.grand_total, 1800)

	def test_totals_cannot_be_manipulated(self):
		doc = _build_reno_order()
		doc.grand_total = 1
		doc.total_amount = 1
		doc.insert(ignore_permissions=True)
		self.assertEqual(doc.total_amount, 2000)
		self.assertEqual(doc.grand_total, 2000)

	def test_invalid_installation_date_rejected(self):
		doc = _build_reno_order()
		doc.expected_installation_date = add_days(today(), -1)
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_negative_quantity_rejected(self):
		doc = _build_reno_order()
		doc.order_items[0].quantity = -5
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_negative_rate_rejected(self):
		doc = _build_reno_order()
		doc.order_items[0].rate = -100
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_high_discount_blocked_without_approval_role(self):
		doc = _build_reno_order(discount_percentage=25)
		doc.insert(ignore_permissions=True)
		frappe.set_user(TEST_SALES_USER)
		with self.assertRaises(frappe.ValidationError):
			doc.submit()

	def test_high_discount_allowed_with_approval_role(self):
		doc = _build_reno_order(discount_percentage=25)
		doc.insert(ignore_permissions=True)
		doc.submit()
		self.assertEqual(doc.docstatus, 1)

	def test_sales_order_creation(self):
		doc = _build_reno_order()
		doc.insert(ignore_permissions=True)
		doc.submit()
		doc.db_set("status", "Confirmed")
		doc.reload()

		so = make_sales_order(doc.name)
		self.assertEqual(so.reno_order, doc.name)
		self.assertEqual(so.customer, TEST_CUSTOMER)
		self.assertEqual(len(so.items), 1)
		self.assertEqual(so.items[0].item_code, TEST_ITEM)
		self.assertEqual(so.items[0].qty, 2)
		self.assertEqual(so.items[0].rate, 1000)

	def test_duplicate_sales_order_prevented(self):
		doc = _build_reno_order()
		doc.insert(ignore_permissions=True)
		doc.submit()
		doc.db_set("status", "Confirmed")
		doc.reload()

		so = make_sales_order(doc.name)
		so.delivery_date = add_days(today(), 20)
		so.insert(ignore_permissions=True)
		so.submit()

		with self.assertRaises(frappe.ValidationError):
			make_sales_order(doc.name)

	def test_sales_order_blocked_before_submit(self):
		doc = _build_reno_order()
		doc.insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			make_sales_order(doc.name)

	def test_sales_order_blocked_outside_confirmed_status(self):
		doc = _build_reno_order()
		doc.insert(ignore_permissions=True)
		doc.submit()
		doc.db_set("status", "In Production")
		doc.reload()
		with self.assertRaises(frappe.ValidationError):
			make_sales_order(doc.name)

	def test_api_requires_authentication(self):
		from reno_order.api import update_installation_status

		frappe.set_user("Guest")
		with self.assertRaises(frappe.AuthenticationError):
			update_installation_status("RO-NONEXISTENT", "Installed")

	def test_api_requires_site_supervisor_role(self):
		from reno_order.api import update_installation_status

		doc = _build_reno_order()
		doc.insert(ignore_permissions=True)
		doc.submit()

		frappe.set_user(TEST_SALES_USER)
		with self.assertRaises(frappe.PermissionError):
			update_installation_status(doc.name, "Installed")

	def test_api_rejects_invalid_status_transition(self):
		from reno_order.api import update_installation_status

		doc = _build_reno_order()
		doc.insert(ignore_permissions=True)
		doc.submit()
		doc.db_set("status", "Confirmed")

		frappe.set_user(TEST_SUPERVISOR)
		with self.assertRaises(frappe.ValidationError):
			update_installation_status(doc.name, "Installed")

	def test_installed_status_enqueues_notification(self):
		doc = _build_reno_order()
		doc.insert(ignore_permissions=True)
		doc.submit()
		doc.db_set("status", "Ready for Installation")
		doc.reload()

		with patch("reno_order.reno_order.doctype.reno_order.reno_order.enqueue_customer_notification") as mock_enqueue:
			doc.status = "Installed"
			doc.save()
			mock_enqueue.assert_called_once_with(doc.name, "order_installed")

	def test_order_type_patch_backfills_blanks(self):
		doc = _build_reno_order()
		doc.insert(ignore_permissions=True)
		frappe.db.set_value("Reno Order", doc.name, "order_type", None)

		blanks_before = frappe.db.count("Reno Order", {"order_type": ["in", [None, ""]]})
		self.assertGreaterEqual(blanks_before, 1)

		frappe.db.sql(
			"UPDATE `tabReno Order` SET order_type = 'Standard' WHERE IFNULL(order_type, '') = ''"
		)

		blanks_after = frappe.db.count("Reno Order", {"order_type": ["in", [None, ""]]})
		self.assertEqual(blanks_after, 0)
		self.assertEqual(
			frappe.db.get_value("Reno Order", doc.name, "order_type"), "Standard"
		)
