import frappe

def execute(filters=None):
    columns = [
        {"label": "Material Request", "fieldname": "material_request", "fieldtype": "Link", "options": "Material Request", "width": 160},
        {"label": "MR Date", "fieldname": "mr_date", "fieldtype": "Date", "width": 100},
        {"label": "MR Status", "fieldname": "mr_status", "fieldtype": "Data", "width": 110},
        {"label": "Connected RFI(s)", "fieldname": "rfi", "fieldtype": "Data", "width": 150},
        {"label": "Connected RFQ(s)", "fieldname": "rfq", "fieldtype": "Data", "width": 220},
        {"label": "Supplier Quotation(s)", "fieldname": "supplier_quotation", "fieldtype": "Data", "width": 220},
        {"label": "Purchase Order(s)", "fieldname": "purchase_order", "fieldtype": "Data", "width": 220},
        {"label": "Total PO Value", "fieldname": "total_po_value", "fieldtype": "Currency", "width": 130},
        {"label": "Purchase Invoice(s)", "fieldname": "purchase_invoice", "fieldtype": "Data", "width": 200}
    ]

    data = []
    mr_list = frappe.get_all("Material Request", fields=["name", "transaction_date", "status"], order_by="modified desc", limit=50)

    for mr in mr_list:
        # Find RFIs
        rfis = frappe.get_all("RFI", filters={"material_request": mr.name}, fields=["name", "status"])
        rfi_str = ", ".join([r.name for r in rfis]) if rfis else "-"
        
        # Find RFQs
        rfq_items = frappe.get_all("Request for Quotation Item", filters={"material_request": mr.name}, fields=["parent"], group_by="parent")
        rfq_list = [r.parent for r in rfq_items]
        rfq_str = ", ".join(rfq_list) if rfq_list else "-"

        # Find Supplier Quotations
        sq_items = frappe.get_all("Supplier Quotation Item", filters={"material_request": mr.name}, fields=["parent"], group_by="parent")
        sq_list = [s.parent for s in sq_items]
        sq_str = ", ".join(sq_list) if sq_list else "-"

        # Find Purchase Orders
        po_items = frappe.get_all("Purchase Order Item", filters={"material_request": mr.name}, fields=["parent"], group_by="parent")
        po_list = [p.parent for p in po_items]
        po_str = ", ".join(po_list) if po_list else "-"
        
        total_po_val = 0.0
        if po_list:
            res = frappe.db.sql("SELECT SUM(grand_total) as total FROM `tabPurchase Order` WHERE name IN %s AND docstatus=1", (po_list,), as_dict=True)
            if res and res[0].total:
                total_po_val = res[0].total

        # Find Purchase Invoices
        inv_str = "-"
        if po_list:
            inv_items = frappe.get_all("Purchase Invoice Item", filters={"purchase_order": ["in", po_list]}, fields=["parent"], group_by="parent")
            if inv_items:
                inv_str = ", ".join([i.parent for i in inv_items])

        data.append({
            "material_request": mr.name,
            "mr_date": mr.transaction_date,
            "mr_status": mr.status,
            "rfi": rfi_str,
            "rfq": rfq_str,
            "supplier_quotation": sq_str,
            "purchase_order": po_str,
            "total_po_value": total_po_val,
            "purchase_invoice": inv_str
        })

    return columns, data
