# Copyright (c) 2026, ERPNext AI Team and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class AIMCPSettings(Document):
	def validate(self):
		if self.max_payload_size_kb is not None and self.max_payload_size_kb <= 0:
			frappe.throw("Max Response Payload Size (KB) must be greater than 0.")
		if self.max_requests_per_minute is not None and self.max_requests_per_minute <= 0:
			frappe.throw("Max Requests per Minute must be greater than 0.")

