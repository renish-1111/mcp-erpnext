"""
Real-Time Event Webhooks for AI MCP Integration.
Triggers webhooks/notifications to external AI agents on critical ERPNext document events
(e.g., Purchase Order submission, Material Request creation/submission, low stock alerts).
"""

import json
import urllib.request
import urllib.parse
import frappe

def send_webhook(event_type: str, payload: dict, webhook_url: str = None) -> dict:
    """
    Send JSON payload via HTTP POST to the AI agent webhook endpoint.
    Safely catches exceptions to ensure ERPNext transactions are not blocked.
    """
    if not webhook_url:
        webhook_url = frappe.conf.get("ai_agent_webhook_url") or "http://localhost:8000/webhook"
        
    full_payload = {
        "event_type": event_type,
        "site": getattr(frappe.local, "site", "ai.local"),
        "timestamp": frappe.utils.now() if hasattr(frappe, "utils") and hasattr(frappe.utils, "now") else None,
        "data": payload
    }
    
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Frappe-AI-MCP-Webhook/1.0"
    }
    
    try:
        data_bytes = json.dumps(full_payload, default=str).encode("utf-8")
        req = urllib.request.Request(webhook_url, data=data_bytes, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            status_code = resp.getcode()
            response_body = resp.read().decode("utf-8")
            
        frappe.logger("ai_mcp").info(f"Webhook {event_type} sent successfully to {webhook_url} (HTTP {status_code})")
        return {"status": "success", "http_status": status_code, "response": response_body}
    except Exception as e:
        frappe.logger("ai_mcp").error(f"Failed to send webhook {event_type} to {webhook_url}: {str(e)}")
        try:
            frappe.log_error(title=f"AI MCP Webhook Error [{event_type}]", message=str(e))
        except Exception:
            pass
        return {"status": "error", "error": str(e)}

def on_purchase_order_submit(doc, method=None):
    """
    Triggered when a Purchase Order is submitted in Frappe/ERPNext.
    Notifies AI agent endpoint about critical / high-value purchase orders.
    """
    items = []
    if hasattr(doc, "items") and doc.items:
        for item in doc.items:
            items.append({
                "item_code": getattr(item, "item_code", None),
                "item_name": getattr(item, "item_name", None),
                "qty": getattr(item, "qty", 0),
                "rate": getattr(item, "rate", 0.0),
                "amount": getattr(item, "amount", 0.0),
                "warehouse": getattr(item, "warehouse", None)
            })
            
    grand_total = float(getattr(doc, "grand_total", 0.0) or 0.0)
    high_value_threshold = float(frappe.conf.get("high_value_po_threshold") or 10000.0)
    is_high_value = grand_total >= high_value_threshold
    
    payload = {
        "doctype": doc.doctype,
        "name": doc.name,
        "supplier": getattr(doc, "supplier", None),
        "grand_total": grand_total,
        "currency": getattr(doc, "currency", "USD"),
        "status": getattr(doc, "status", "Submitted"),
        "docstatus": doc.docstatus,
        "is_high_value": is_high_value,
        "items": items,
        "company": getattr(doc, "company", None)
    }
    
    event_type = "purchase_order_submitted_high_value" if is_high_value else "purchase_order_submitted"
    send_webhook(event_type=event_type, payload=payload)

def on_material_request_submit(doc, method=None):
    """
    Triggered when a Material Request is submitted in Frappe/ERPNext.
    Notifies AI agent endpoint about stock replenishment / reorder events.
    """
    items = []
    if hasattr(doc, "items") and doc.items:
        for item in doc.items:
            items.append({
                "item_code": getattr(item, "item_code", None),
                "item_name": getattr(item, "item_name", None),
                "qty": getattr(item, "qty", 0),
                "warehouse": getattr(item, "warehouse", None)
            })
            
    payload = {
        "doctype": doc.doctype,
        "name": doc.name,
        "material_request_type": getattr(doc, "material_request_type", None),
        "docstatus": doc.docstatus,
        "status": getattr(doc, "status", "Submitted"),
        "items": items,
        "company": getattr(doc, "company", None)
    }
    
    send_webhook(event_type="material_request_submitted", payload=payload)

def notify_low_stock(item_code: str, warehouse: str, actual_qty: float, min_qty: float):
    """
    Explicit helper function to trigger a low stock webhook alert to AI endpoints.
    """
    payload = {
        "item_code": item_code,
        "warehouse": warehouse,
        "actual_qty": actual_qty,
        "min_qty": min_qty
    }
    return send_webhook(event_type="low_stock_alert", payload=payload)
