# Copyright (c) 2026, ERPNext AI Team and contributors
# For license information, please see license.txt

import os
import unittest
import openpyxl
import frappe
from ai_mcp.smart_import_engine import SmartImportEngine


class TestSmartDataImport(unittest.TestCase):

	def setUp(self):
		frappe.set_user("Administrator")

	def test_topological_sort_dag(self):
		"""
		Tests that Inter-DocType DAG topological sort places independent DocTypes
		in Tier 0 and dependent DocTypes in Tier 1, 2, etc.
		"""
		engine = SmartImportEngine.__new__(SmartImportEngine)
		target_doctypes = {"Customer Group", "Customer", "Sales Order"}
		tiers = engine.build_topological_dependency_tiers(target_doctypes)

		tier_map = {t["doctype"]: t["tier"] for t in tiers}
		
		# Customer Group has 0 dependencies -> Tier 0
		# Customer depends on Customer Group -> Tier 1
		# Sales Order depends on Customer -> Tier 2
		self.assertIn("Customer Group", tier_map)
		self.assertIn("Customer", tier_map)
		self.assertIn("Sales Order", tier_map)
		self.assertLess(tier_map["Customer Group"], tier_map["Customer"])
		self.assertLess(tier_map["Customer"], tier_map["Sales Order"])

	def test_inner_dependency_detection(self):
		"""
		Tests that self-referential links (e.g. parent link in Item Group) are detected.
		"""
		engine = SmartImportEngine.__new__(SmartImportEngine)
		tiers = engine.build_topological_dependency_tiers({"Item Group"})
		
		item_group_info = next(t for t in tiers if t["doctype"] == "Item Group")
		self.assertIsNotNone(item_group_info["inner_ref_field"])


	def test_file_doctype_autodetect(self):
		"""
		Tests auto-detection of target DocType from filename.
		"""
		engine = SmartImportEngine.__new__(SmartImportEngine)
		dt = engine.detect_target_doctype("Customer.xlsx", "Sheet1", ["customer_name", "customer_group"])
		self.assertEqual(dt, "Customer")

	def test_end_to_end_batch_import(self):
		"""
		Tests end-to-end batch import with Excel files for Customer Group and Customer.
		"""
		import tempfile
		group_name = f"Test Batch Group {frappe.generate_hash(length=6)}"
		wb1 = openpyxl.Workbook()
		ws1 = wb1.active
		ws1.title = "Customer Group"
		ws1.append(["customer_group_name"])
		ws1.append([group_name])
		file1_path = os.path.join(tempfile.gettempdir(), "Customer Group.xlsx")
		wb1.save(file1_path)
		wb1.close()


		# Save File in Frappe
		f1 = frappe.get_doc({
			"doctype": "File",
			"file_name": "Customer Group.xlsx",
			"content": open(file1_path, "rb").read(),
			"is_private": 0
		}).insert(ignore_permissions=True)

		# Create Smart Data Import Doc
		sdi = frappe.get_doc({
			"doctype": "Smart Data Import",
			"title": "E2E Batch Import Test",
			"batch_size": 100,
			"files": [
				{
					"file": f1.file_url,
					"doctype_name": "Customer Group",
					"sheet_name": "Customer Group"
				}
			]
		}).insert(ignore_permissions=True)

		# Run Analysis
		engine = SmartImportEngine(sdi)
		engine.analyze_files_and_build_graph()
		self.assertEqual(sdi.status, "Ready")
		self.assertGreater(len(sdi.dependencies), 0)

		# Execute Import
		success = engine.execute_import()
		self.assertTrue(success)

		self.assertIn(sdi.status, ["Completed", "Partial Success"])
		self.assertGreaterEqual(sdi.imported_records, 1)


		# Clean up test records
		frappe.db.rollback()

	def test_ignore_duplicates(self):
		"""
		Tests that ignore_duplicates skips duplicate primary keys without failing.
		"""
		engine = SmartImportEngine.__new__(SmartImportEngine)
		engine.ignore_duplicates = True
		engine.ignore_link_errors = True
		engine.stop_on_error = False

		meta = frappe.get_meta("Customer Group")
		group_name = "All Customer Groups"  # Existing standard Customer Group

		batch = [(2, {"customer_group_name": group_name})]
		c_success, c_failed, errors = engine._flush_batch_to_db("Customer Group", batch, meta)
		
		# Should skip existing record, failed count should be 0
		self.assertEqual(c_failed, 0)
		self.assertEqual(len(errors), 0)



if __name__ == "__main__":
	unittest.main()
