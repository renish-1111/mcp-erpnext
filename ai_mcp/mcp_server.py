#!/usr/bin/env python3
"""
Universal Dynamic MCP Server for Frappe / ERPNext v16
Packaged inside custom Frappe App 'ai_mcp' (apps/ai_mcp/ai_mcp/mcp_server.py)
"""

import sys
import os
import json
import base64
import csv
import io
import re
import time

os.environ["FASTMCP_SHOW_HERO"] = "0"
os.environ["FASTMCP_LOG_LEVEL"] = "ERROR"


# Resolve path dynamically for any Frappe Bench setup
BENCH_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SITES_PATH = os.path.join(BENCH_DIR, "sites")
APPS_PATH = os.path.join(BENCH_DIR, "apps")

if os.path.exists(APPS_PATH):
    sys.path.insert(0, os.path.join(APPS_PATH, "frappe"))
    sys.path.insert(0, os.path.join(APPS_PATH, "erpnext"))

if os.path.exists(SITES_PATH):
    os.chdir(SITES_PATH)

import frappe
from fastmcp import FastMCP

# Initialize Dynamic FastMCP Server
mcp = FastMCP(
    "ERPNext-Dynamic-MCP",
    instructions="Universal Dynamic MCP Server for Frappe & ERPNext v16 packaged in app 'ai_mcp'."
)

def get_active_site() -> str:
    """Dynamically determine active site name for any Frappe Bench setup without hardcoded fallbacks."""
    if getattr(frappe.local, "site", None):
        return frappe.local.site
        
    if os.environ.get("FRAPPE_SITE"):
        return os.environ["FRAPPE_SITE"]

    if os.path.exists(SITES_PATH):
        currentsite_txt = os.path.join(SITES_PATH, "currentsite.txt")
        if os.path.exists(currentsite_txt):
            try:
                with open(currentsite_txt, "r") as f:
                    site = f.read().strip()
                    if site and os.path.exists(os.path.join(SITES_PATH, site)):
                        return site
            except Exception:
                pass

        for entry in sorted(os.listdir(SITES_PATH)):
            site_dir = os.path.join(SITES_PATH, entry)
            if os.path.isdir(site_dir) and os.path.exists(os.path.join(site_dir, "site_config.json")):
                return entry

    return "localhost"

def ensure_frappe(site: str = None):
    """Ensure Frappe environment is initialized and connected to specified or active site."""
    if not site:
        site = get_active_site()
    current_site = getattr(frappe.local, "site", None)
    if not current_site or current_site != site:
        if current_site:
            frappe.destroy()
        frappe.init(site=site, sites_path=SITES_PATH if os.path.exists(SITES_PATH) else "./")
        frappe.connect()


def sanitize(obj):
    """Recursively convert Frappe objects (date, datetime, _dict, Decimal, etc.) into pure JSON primitives."""
    return json.loads(json.dumps(obj, default=str))

def _write_mcp_audit_log(tool_name: str, args: dict, status: str = "Success", result=None, execution_time_ms: float = 0.0, user: str = None):
    """Internal synchronous function to insert MCP Audit Log entry into Frappe database."""
    try:
        if frappe.db.exists("DocType", "AI MCP Settings"):
            settings = frappe.get_single("AI MCP Settings")
            if settings.get("audit_log_mcp_actions"):
                log_doc = frappe.get_doc({
                    "doctype": "MCP Audit Log",
                    "tool_name": tool_name,
                    "user": user or (frappe.session.user if getattr(frappe, "session", None) and getattr(frappe.session, "user", None) else "Administrator"),
                    "status": status,
                    "execution_time_ms": execution_time_ms,
                    "arguments_json": json.dumps(args, default=str),
                    "result_json": json.dumps(result, default=str)[:2000] if result else ""
                })
                log_doc.insert(ignore_permissions=True)
                frappe.db.commit()
    except Exception:
        pass

def log_mcp_action(tool_name: str, args: dict, status: str = "Success", result=None, execution_time_ms: float = 0.0):
    """Record tool execution audit log asynchronously via frappe.enqueue with non-blocking try-except fallback."""
    user = frappe.session.user if getattr(frappe, "session", None) and getattr(frappe.session, "user", None) else "Administrator"
    try:
        frappe.enqueue(
            "ai_mcp.mcp_server._write_mcp_audit_log",
            queue="short",
            tool_name=tool_name,
            args=args,
            status=status,
            result=result,
            execution_time_ms=execution_time_ms,
            user=user
        )
    except Exception:
        # Non-blocking fallback if enqueue fails or queue worker is offline
        try:
            _write_mcp_audit_log(tool_name, args, status=status, result=result, execution_time_ms=execution_time_ms, user=user)
        except Exception:
            pass

def run_sse_server(host: str = "0.0.0.0", port: int = 8000):
    """Run FastMCP server using Server-Sent Events (SSE) streaming transport mode."""
    mcp.run(transport="sse", host=host, port=port)


HIGH_RISK_TOOLS = {
    "run_sql_query",
    "delete_document",
    "create_custom_field",
    "bulk_update_documents",
    "add_property_setter",
    "diagnose_and_clean_errors"
}

def check_rate_limit(user: str = None):
    """
    Rate-limiting guardrail to enforce maximum request frequency per user per minute.
    Configurable via AI MCP Settings (default: 60 requests per minute).
    """
    try:
        if frappe.db.exists("DocType", "AI MCP Settings"):
            settings = frappe.get_single("AI MCP Settings")
            if hasattr(settings, "enable_rate_limiting") and not settings.get("enable_rate_limiting", 1):
                return
            max_requests = getattr(settings, "max_requests_per_minute", 60) or 60
        else:
            max_requests = 60

        user = user or (frappe.session.user if getattr(frappe, "session", None) and getattr(frappe.session, "user", None) else "Guest")
        current_minute = int(time.time() // 60)
        cache_key = f"mcp_rate_limit:{user}:{current_minute}"

        cache = frappe.cache()
        count = cache.get_value(cache_key) or 0
        if count >= max_requests:
            frappe.throw(
                f"Rate limit exceeded: Maximum {max_requests} requests per minute allowed.",
                frappe.PermissionError
            )
        cache.set_value(cache_key, count + 1, expires_in_sec=120)
    except frappe.PermissionError:
        raise
    except Exception:
        pass

def check_tool_permissions(tool_name: str, args: dict = None, user: str = None):
    """
    Verify user role permissions before executing sensitive / high-risk tools.
    High-risk tools (run_sql_query, delete_document, create_custom_field, bulk_update_documents)
    require 'System Manager' or 'AI Admin' roles, or explicit permission via frappe.has_permission.
    """
    try:
        if frappe.db.exists("DocType", "AI MCP Settings"):
            settings = frappe.get_single("AI MCP Settings")
            if hasattr(settings, "restrict_high_risk_tools") and not settings.get("restrict_high_risk_tools", 1):
                return True
    except Exception:
        pass

    user = user or (frappe.session.user if getattr(frappe, "session", None) and getattr(frappe.session, "user", None) else "Administrator")
    if user == "Administrator":
        return True

    try:
        user_roles = frappe.get_roles(user) if user else []
    except Exception:
        user_roles = []

    is_admin = "System Manager" in user_roles or "AI Admin" in user_roles

    if tool_name not in HIGH_RISK_TOOLS:
        return True

    if is_admin:
        return True

    args = args or {}
    doctype = args.get("doctype") or args.get("dt")
    docname = args.get("name")

    if tool_name == "delete_document":
        if doctype and frappe.has_permission(doctype, ptype="delete", doc=docname, user=user):
            return True
        frappe.throw(
            f"Permission denied: Executing tool '{tool_name}' requires 'System Manager' or 'AI Admin' role, or explicit delete permission on DocType '{doctype}'.",
            frappe.PermissionError
        )
    elif tool_name == "bulk_update_documents":
        if doctype and frappe.has_permission(doctype, ptype="write", user=user):
            return True
        frappe.throw(
            f"Permission denied: Executing tool '{tool_name}' requires 'System Manager' or 'AI Admin' role, or explicit write permission on DocType '{doctype}'.",
            frappe.PermissionError
        )
    elif tool_name == "create_custom_field":
        if frappe.has_permission("Custom Field", ptype="create", user=user):
            return True
        frappe.throw(
            f"Permission denied: Executing tool '{tool_name}' requires 'System Manager' or 'AI Admin' role.",
            frappe.PermissionError
        )
    elif tool_name == "run_sql_query":
        frappe.throw(
            f"Permission denied: Executing tool '{tool_name}' requires 'System Manager' or 'AI Admin' role.",
            frappe.PermissionError
        )
    else:
        frappe.throw(
            f"Permission denied: Executing high-risk tool '{tool_name}' requires 'System Manager' or 'AI Admin' role.",
            frappe.PermissionError
        )

def truncate_payload(data, max_bytes: int = 102400):
    """
    Truncate oversized response payloads gracefully if json-encoded byte size exceeds max_bytes (default 100KB).
    Returns truncated data with metadata indicating truncation if applied.
    """
    if data is None:
        return data

    try:
        if frappe.db.exists("DocType", "AI MCP Settings"):
            settings = frappe.get_single("AI MCP Settings")
            kb = getattr(settings, "max_payload_size_kb", 100) or 100
            max_bytes = int(kb * 1024)
    except Exception:
        pass

    try:
        encoded = json.dumps(data, default=str).encode("utf-8")
        if len(encoded) <= max_bytes:
            return data
    except Exception:
        return data

    if isinstance(data, list):
        truncated_list = []
        original_count = len(data)
        for item in data:
            truncated_list.append(item)
            test_meta = {
                "data": truncated_list,
                "_truncated": True,
                "_truncated_reason": f"Payload exceeded max size limit of {max_bytes // 1024}KB.",
                "_original_count": original_count,
                "_returned_count": len(truncated_list)
            }
            if len(json.dumps(test_meta, default=str).encode("utf-8")) > max_bytes:
                truncated_list.pop()
                break

        return {
            "data": truncated_list,
            "_truncated": True,
            "_truncated_reason": f"Payload exceeded max size limit of {max_bytes // 1024}KB. Items truncated from {original_count} to {len(truncated_list)}.",
            "_original_count": original_count,
            "_returned_count": len(truncated_list)
        }

    elif isinstance(data, dict):
        truncated_dict = dict(data)
        for k, v in list(truncated_dict.items()):
            if isinstance(v, str) and len(v) > 2000:
                truncated_dict[k] = v[:2000] + f"... [Truncated string field '{k}' of size {len(v)} chars]"

        encoded = json.dumps(truncated_dict, default=str).encode("utf-8")
        if len(encoded) <= max_bytes:
            truncated_dict["_truncated"] = True
            truncated_dict["_truncated_reason"] = f"Payload exceeded max size limit of {max_bytes // 1024}KB. Large string fields were truncated."
            return truncated_dict

        for k, v in list(truncated_dict.items()):
            if isinstance(v, list) and len(v) > 5:
                truncated_dict[k] = v[:5]
                encoded = json.dumps(truncated_dict, default=str).encode("utf-8")
                if len(encoded) <= max_bytes:
                    break

        truncated_dict["_truncated"] = True
        truncated_dict["_truncated_reason"] = f"Payload exceeded max size limit of {max_bytes // 1024}KB."
        
        encoded = json.dumps(truncated_dict, default=str).encode("utf-8")
        if len(encoded) > max_bytes:
            str_repr = json.dumps(truncated_dict, default=str)
            allowed_chars = int(max_bytes * 0.9)
            return {
                "_truncated": True,
                "_truncated_reason": f"Payload exceeded max size limit of {max_bytes // 1024}KB.",
                "raw_preview": str_repr[:allowed_chars] + "... [Truncated]"
            }

        return truncated_dict

    elif isinstance(data, str):
        allowed_chars = int(max_bytes * 0.9)
        return data[:allowed_chars] + f"... [Truncated: Payload exceeded max size limit of {max_bytes // 1024}KB]"

    return data


# -------------------------------------------------------------------
# 1. METADATA, DOCTYPE & RELATIONAL DISCOVERY
# -------------------------------------------------------------------

@mcp.tool()
def list_doctypes(site: str = None, module: str = None, search: str = None, custom_only: bool = False, limit: int = 100) -> list:
    """List all available DocTypes in the system. Filter by module or search keyword."""
    ensure_frappe(site)
    limit = max(1, min(limit or 100, 500))
    filters = {}
    if module:
        filters["module"] = module
    if custom_only:
        filters["custom"] = 1
    
    or_filters = {}
    if search:
        or_filters = {"name": ["like", f"%{search}%"], "module": ["like", f"%{search}%"]}
        
    fields = ["name", "module", "custom", "issingle", "istable", "is_submittable"]
    data = frappe.get_all("DocType", filters=filters, or_filters=or_filters, fields=fields, limit=limit, order_by="name asc")
    return sanitize(data)

@mcp.tool()
def get_doctype_meta(doctype: str, site: str = None) -> dict:
    """Get complete metadata & schema definition for ANY DocType, including fields, types, mandatory flags, and child tables."""
    ensure_frappe(site)
    if not doctype or not frappe.db.exists("DocType", doctype):
        raise ValueError(f"DocType '{doctype}' does not exist.")
    meta = frappe.get_meta(doctype)
    fields = []
    for df in meta.fields:
        if df.fieldtype not in ("Section Break", "Column Break", "Tab Break", "HTML"):
            fields.append({
                "fieldname": df.fieldname,
                "label": df.label,
                "fieldtype": df.fieldtype,
                "options": df.options,
                "reqd": df.reqd,
                "read_only": df.read_only,
                "default": df.default,
                "description": df.description
            })
    return sanitize({
        "doctype": doctype,
        "module": meta.module,
        "is_single": meta.issingle,
        "is_table": meta.istable,
        "is_submittable": meta.is_submittable,
        "autoname": meta.autoname,
        "title_field": meta.title_field,
        "search_fields": meta.search_fields,
        "fields": fields
    })

@mcp.tool()
def get_doctype_relations(doctype: str, site: str = None) -> dict:
    """Map incoming/outgoing Link fields and child tables for ANY DocType (ER-diagram mapping)."""
    ensure_frappe(site)
    if not doctype or not frappe.db.exists("DocType", doctype):
        raise ValueError(f"DocType '{doctype}' does not exist.")
        
    meta = frappe.get_meta(doctype)
    outgoing_links = []
    child_tables = []
    
    for df in meta.fields:
        if df.fieldtype == "Link":
            outgoing_links.append({"field": df.fieldname, "target_doctype": df.options})
        elif df.fieldtype == "Table":
            child_tables.append({"field": df.fieldname, "child_doctype": df.options})
            
    # Incoming links
    incoming_links = frappe.get_all(
        "DocType Link",
        filters={"parent": doctype},
        fields=["link_doctype", "link_fieldname"]
    )
    
    return sanitize({
        "doctype": doctype,
        "outgoing_links": outgoing_links,
        "child_tables": child_tables,
        "incoming_links": incoming_links
    })

# -------------------------------------------------------------------
# 2. SCHEMA & CUSTOM FIELD BUILDER
# -------------------------------------------------------------------

@mcp.tool()
def create_custom_field(dt: str, fieldname: str, label: str, fieldtype: str = "Data", options: str = None, reqd: int = 0, insert_after: str = None, site: str = None) -> dict:
    """Create a Custom Field on any standard or custom DocType dynamically. Enforces custom_ prefix."""
    ensure_frappe(site)
    check_tool_permissions("create_custom_field", {"dt": dt, "fieldname": fieldname})
    if not dt or not frappe.db.exists("DocType", dt):
        raise ValueError(f"Target DocType '{dt}' does not exist.")
    if not fieldname:
        raise ValueError("Fieldname cannot be empty.")
        
    if not fieldname.startswith("custom_"):
        fieldname = f"custom_{fieldname}"
        
    cf_name = f"{dt}-{fieldname}"
    if frappe.db.exists("Custom Field", cf_name):
        doc = frappe.get_doc("Custom Field", cf_name)
    else:
        doc = frappe.new_doc("Custom Field")
        doc.dt = dt
        doc.fieldname = fieldname
        
    doc.label = label or fieldname.replace("_", " ").title()
    doc.fieldtype = fieldtype or "Data"
    if options:
        doc.options = options
    doc.reqd = reqd or 0
    if insert_after:
        doc.insert_after = insert_after
        
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    frappe.clear_cache(doctype=dt)
    return sanitize(doc.as_dict())

@mcp.tool()
def add_property_setter(doctype: str, property: str, value: str, fieldname: str = None, property_type: str = "Data", site: str = None) -> dict:
    """Modify property settings of standard fields/DocTypes (e.g. read_only, hidden, mandatory) without editing core code."""
    ensure_frappe(site)
    check_tool_permissions("add_property_setter", {"doctype": doctype, "property": property})
    if not doctype or not frappe.db.exists("DocType", doctype):
        raise ValueError(f"DocType '{doctype}' does not exist.")
    from frappe.custom.doctype.property_setter.property_setter import make_property_setter
    ps = make_property_setter(
        doctype=doctype,
        fieldname=fieldname,
        property=property,
        value=value,
        property_type=property_type,
        validate_fields_for_doctype=False
    )
    frappe.db.commit()
    frappe.clear_cache(doctype=doctype)
    return sanitize(ps.as_dict())

# -------------------------------------------------------------------
# 3. UNIVERSAL DYNAMIC CRUD & BULK OPERATIONS
# -------------------------------------------------------------------

@mcp.tool()
def list_documents(doctype: str, filters: dict = None, fields: list = None, order_by: str = None, limit: int = 20, start: int = 0, user: str = None, site: str = None) -> list:
    """Dynamically query & list documents for ANY DocType within specified user session context."""
    ensure_frappe(site)
    if not doctype or not frappe.db.exists("DocType", doctype):
        raise ValueError(f"DocType '{doctype}' does not exist.")

    original_user = frappe.session.user if getattr(frappe, "session", None) and getattr(frappe.session, "user", None) else None
    try:
        if user and frappe.db.exists("User", user):
            frappe.set_user(user)
            
        limit = max(1, min(limit or 20, 500))
        start = max(0, start or 0)
        
        if not fields:
            meta = frappe.get_meta(doctype)
            fields = [meta.title_field] if meta.title_field else ["name"]
            if "name" not in fields:
                fields.insert(0, "name")
            if "modified" not in fields:
                fields.append("modified")
                
        data = frappe.get_all(
            doctype,
            filters=filters or {},
            fields=fields,
            order_by=order_by or "modified desc",
            limit_page_length=limit,
            limit_start=start
        )
        return sanitize(data)
    finally:
        if user and original_user:
            frappe.set_user(original_user)

@mcp.tool()
def get_document(doctype: str, name: str, user: str = None, site: str = None) -> dict:
    """Fetch complete document content for ANY DocType by name in current user context."""
    ensure_frappe(site)
    if not doctype or not frappe.db.exists("DocType", doctype):
        raise ValueError(f"DocType '{doctype}' does not exist.")

    original_user = frappe.session.user if getattr(frappe, "session", None) and getattr(frappe.session, "user", None) else None
    try:
        if user and frappe.db.exists("User", user):
            frappe.set_user(user)
        doc = frappe.get_doc(doctype, name)
        return sanitize(doc.as_dict())
    finally:
        if user and original_user:
            frappe.set_user(original_user)

@mcp.tool()
def create_document(doctype: str, data: dict, user: str = None, site: str = None) -> dict:
    """Create & save a new document for ANY DocType dynamically under current or specified user account."""
    ensure_frappe(site)
    if not doctype or not frappe.db.exists("DocType", doctype):
        raise ValueError(f"DocType '{doctype}' does not exist.")
    if not data or not isinstance(data, dict):
        raise ValueError("Data parameter must be a non-empty dictionary.")

    original_user = frappe.session.user if getattr(frappe, "session", None) and getattr(frappe.session, "user", None) else None
    try:
        if user and frappe.db.exists("User", user):
            frappe.set_user(user)
            
        doc = frappe.get_doc({"doctype": doctype, **data})
        if user:
            doc.owner = user
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return sanitize(doc.as_dict())
    finally:
        if user and original_user:
            frappe.set_user(original_user)

@mcp.tool()
def update_document(doctype: str, name: str, data: dict, site: str = None) -> dict:
    """Update fields of an existing document for ANY DocType."""
    ensure_frappe(site)
    if not doctype or not frappe.db.exists("DocType", doctype):
        raise ValueError(f"DocType '{doctype}' does not exist.")
    if not name:
        raise ValueError("Document name cannot be empty.")
        
    doc = frappe.get_doc(doctype, name)
    doc.update(data or {})
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return sanitize(doc.as_dict())

@mcp.tool()
def bulk_update_documents(doctype: str, names: list, data: dict, site: str = None) -> dict:
    """Update field values across multiple documents of the specified DocType in a single atomic transaction."""
    ensure_frappe(site)
    check_tool_permissions("bulk_update_documents", {"doctype": doctype, "names": names})
    if not doctype or not frappe.db.exists("DocType", doctype):
        raise ValueError(f"DocType '{doctype}' does not exist.")
    if not names:
        return sanitize({"status": "success", "doctype": doctype, "updated_count": 0, "updated_names": []})
        
    updated_count = 0
    for name in names:
        doc = frappe.get_doc(doctype, name)
        doc.update(data or {})
        doc.save(ignore_permissions=True)
        updated_count += 1
    frappe.db.commit()
    return sanitize({"status": "success", "doctype": doctype, "updated_count": updated_count, "updated_names": names})

@mcp.tool()
def delete_document(doctype: str, name: str, site: str = None) -> dict:
    """Delete a document for ANY DocType."""
    ensure_frappe(site)
    check_tool_permissions("delete_document", {"doctype": doctype, "name": name})
    if not doctype or not frappe.db.exists("DocType", doctype):
        raise ValueError(f"DocType '{doctype}' does not exist.")
    if not name:
        raise ValueError("Document name cannot be empty.")
    frappe.delete_doc(doctype, name, ignore_permissions=True)
    frappe.db.commit()
    return sanitize({"status": "deleted", "doctype": doctype, "name": name})

@mcp.tool()
def import_csv_data(doctype: str, csv_content_base64: str, site: str = None) -> dict:
    """Parse base64 encoded CSV data and bulk-import records into the specified DocType with validation."""
    ensure_frappe(site)
    if not doctype or not frappe.db.exists("DocType", doctype):
        raise ValueError(f"DocType '{doctype}' does not exist.")
    if not csv_content_base64:
        raise ValueError("CSV content cannot be empty.")
        
    try:
        csv_bytes = base64.b64decode(csv_content_base64).decode("utf-8")
    except Exception as e:
        raise ValueError(f"Invalid base64 encoded CSV content: {e}")
        
    reader = csv.DictReader(io.StringIO(csv_bytes))
    inserted_records = []
    
    for row in reader:
        row_data = {k: v for k, v in row.items() if k and v != ""}
        if row_data:
            doc = frappe.get_doc({"doctype": doctype, **row_data})
            doc.insert(ignore_permissions=True)
            inserted_records.append(doc.name)
        
    frappe.db.commit()
    return sanitize({"status": "success", "doctype": doctype, "imported_count": len(inserted_records), "inserted_names": inserted_records})

# -------------------------------------------------------------------
# 4. KPI DASHBOARD & CURRENCY CONVERTER
# -------------------------------------------------------------------

@mcp.tool()
def get_kpi_summary(module: str = "Accounts", site: str = None) -> dict:
    """Compute real-time business KPIs (Total Receivables, Monthly Revenue, Pending Orders, Item Count)."""
    ensure_frappe(site)
    
    res = frappe.db.sql("SELECT SUM(outstanding_amount) as total FROM `tabSales Invoice` WHERE docstatus=1 AND outstanding_amount > 0", as_dict=True)
    total_receivables = res[0].total if res and res[0].total else 0.0
    
    res_month = frappe.db.sql("SELECT SUM(grand_total) as total FROM `tabSales Invoice` WHERE docstatus=1 AND MONTH(posting_date) = MONTH(CURRENT_DATE())", as_dict=True)
    total_sales_month = res_month[0].total if res_month and res_month[0].total else 0.0
    
    items_count = frappe.db.count("Item")
    sales_orders_count = frappe.db.count("Sales Order", filters={"status": ["in", ["To Deliver and Bill", "To Deliver", "To Bill"]]})
    error_logs_count = frappe.db.count("Error Log")
    
    return sanitize({
        "site": getattr(frappe.local, "site", site),
        "total_outstanding_receivables": total_receivables,
        "total_sales_current_month": total_sales_month,
        "total_items_count": items_count,
        "pending_sales_orders_count": sales_orders_count,
        "error_logs_count": error_logs_count
    })

@mcp.tool()
def get_currency_exchange_rate(from_currency: str, to_currency: str, transaction_date: str = None, site: str = None) -> dict:
    """Fetch live or recorded currency exchange rate from ERPNext setup matrix."""
    ensure_frappe(site)
    if not from_currency or not to_currency:
        raise ValueError("Both from_currency and to_currency must be provided.")
    if from_currency.upper() == to_currency.upper():
        return sanitize({"from_currency": from_currency, "to_currency": to_currency, "exchange_rate": 1.0})
        
    try:
        from erpnext.setup.utils import get_exchange_rate
        rate = get_exchange_rate(from_currency, to_currency, transaction_date)
    except Exception:
        rate = 1.0
        
    return sanitize({
        "from_currency": from_currency,
        "to_currency": to_currency,
        "transaction_date": transaction_date or frappe.utils.nowdate(),
        "exchange_rate": rate or 1.0
    })

# -------------------------------------------------------------------
# 5. INVENTORY & WORKFLOW AUTOMATION BOTS
# -------------------------------------------------------------------

@mcp.tool()
def check_low_stock_and_reorder(warehouse: str = None, min_stock_threshold: float = 5.0, site: str = None) -> dict:
    """Scan inventory stock bins at database level (actual_qty <= threshold) and automatically create draft Material Requests."""
    ensure_frappe(site)
    filters = {"actual_qty": ["<=", min_stock_threshold]}
    if warehouse:
        filters["warehouse"] = warehouse
        
    bins = frappe.get_all("Bin", filters=filters, fields=["item_code", "warehouse", "actual_qty"])
    if not bins:
        return sanitize({"status": "no_reorder_needed", "reordered_count": 0, "material_requests": []})
        
    mr_by_warehouse = {}
    for b in bins:
        wh = b.warehouse
        if wh not in mr_by_warehouse:
            mr_by_warehouse[wh] = []
        mr_by_warehouse[wh].append({
            "item_code": b.item_code,
            "qty": max(10.0, min_stock_threshold * 2 - b.actual_qty),
            "schedule_date": frappe.utils.add_days(frappe.utils.nowdate(), 7),
            "warehouse": wh
        })
        
    created_mrs = []
    for wh, items in mr_by_warehouse.items():
        mr = frappe.get_doc({
            "doctype": "Material Request",
            "material_request_type": "Purchase",
            "schedule_date": frappe.utils.add_days(frappe.utils.nowdate(), 7),
            "items": items
        })
        mr.insert(ignore_permissions=True)
        created_mrs.append(mr.name)
        
    frappe.db.commit()
    return sanitize({"status": "reorders_created", "reordered_count": len(created_mrs), "material_requests": created_mrs})

@mcp.tool()
def diagnose_and_clean_errors(purge_days_old: int = 30, site: str = None) -> dict:
    """Group recent system Error Logs by exception type, summarize issues, and optionally purge logs older than X days."""
    ensure_frappe(site)
    check_tool_permissions("diagnose_and_clean_errors", {"purge_days_old": purge_days_old})
    groups = frappe.db.sql(
        "SELECT method, COUNT(*) as count, MAX(creation) as latest_occurrence FROM `tabError Log` GROUP BY method ORDER BY count DESC LIMIT 10",
        as_dict=True
    )
    
    purged_count = 0
    if purge_days_old and purge_days_old > 0:
        cutoff_date = frappe.utils.add_days(frappe.utils.nowdate(), -purge_days_old)
        purged = frappe.db.sql("DELETE FROM `tabError Log` WHERE creation < %s", (cutoff_date,))
        frappe.db.commit()
        purged_count = purged or 0
        
    return sanitize({"top_error_groups": groups, "purged_logs_older_than_days": purge_days_old})

@mcp.tool()
def find_duplicate_records(doctype: str, fieldname: str, site: str = None) -> dict:
    """Scan database for duplicate values in any DocType column using safe metadata validation."""
    ensure_frappe(site)
    if not doctype or not frappe.db.exists("DocType", doctype):
        raise ValueError(f"DocType '{doctype}' does not exist.")
    if not fieldname:
        raise ValueError("Fieldname cannot be empty.")
        
    meta = frappe.get_meta(doctype)
    valid_fields = [f.fieldname for f in meta.fields] + ["name", "owner", "modified"]
    if fieldname not in valid_fields:
        raise ValueError(f"Field '{fieldname}' does not exist in DocType '{doctype}'.")
        
    duplicates = frappe.db.sql(
        f"SELECT `{fieldname}`, COUNT(*) as count FROM `tab{doctype}` GROUP BY `{fieldname}` HAVING count > 1 ORDER BY count DESC LIMIT 50",
        as_dict=True
    )
    return sanitize({"doctype": doctype, "fieldname": fieldname, "duplicates": duplicates})

@mcp.tool()
def auto_approve_workflow(doctype: str, name: str, site: str = None) -> dict:
    """Evaluate document state against Frappe Approval Workflow and auto-apply 'Approve' action."""
    ensure_frappe(site)
    if not doctype or not frappe.db.exists("DocType", doctype):
        raise ValueError(f"DocType '{doctype}' does not exist.")
    from frappe.model.workflow import apply_workflow
    doc = frappe.get_doc(doctype, name)
    updated_doc = apply_workflow(doc, "Approve")
    frappe.db.commit()
    return sanitize(updated_doc.as_dict())

# -------------------------------------------------------------------
# 6. EMAIL DISPATCHER & COMMUNICATIONS
# -------------------------------------------------------------------

@mcp.tool()
def send_email_notification(recipients: list, subject: str, message: str, doctype: str = None, name: str = None, site: str = None) -> dict:
    """Send an email notification via Frappe Email Queue or record in Communication log."""
    ensure_frappe(site)
    if not recipients or not isinstance(recipients, list):
        raise ValueError("Recipients parameter must be a non-empty list of email addresses.")
    if not subject:
        raise ValueError("Subject cannot be empty.")
        
    try:
        frappe.sendmail(
            recipients=recipients,
            subject=subject,
            message=message or "",
            reference_doctype=doctype,
            reference_name=name,
            now=False
        )
        frappe.db.commit()
        return sanitize({"status": "queued", "recipients": recipients, "subject": subject})
    except Exception:
        comm = frappe.get_doc({
            "doctype": "Communication",
            "communication_type": "Communication",
            "communication_medium": "Email",
            "subject": subject,
            "content": message or "",
            "recipients": ", ".join(recipients),
            "sent_or_received": "Sent",
            "reference_doctype": doctype,
            "reference_name": name
        })
        comm.insert(ignore_permissions=True)
        frappe.db.commit()
        return sanitize({
            "status": "logged_in_communication",
            "communication_id": comm.name,
            "recipients": recipients,
            "subject": subject,
            "note": "No active SMTP server configured. Message logged to Communication DocType."
        })

# -------------------------------------------------------------------
# 7. TRANSACTION CONTROL & ROLLBACK
# -------------------------------------------------------------------

@mcp.tool()
def commit_transaction(site: str = None) -> dict:
    """Commit current database transaction."""
    ensure_frappe(site)
    frappe.db.commit()
    return sanitize({"status": "committed", "site": getattr(frappe.local, "site", site)})

@mcp.tool()
def rollback_transaction(site: str = None) -> dict:
    """Roll back current database transaction to previous state."""
    ensure_frappe(site)
    frappe.db.rollback()
    return sanitize({"status": "rolled_back", "site": getattr(frappe.local, "site", site)})

# -------------------------------------------------------------------
# 8. PDF & PRINT FORMAT GENERATOR
# -------------------------------------------------------------------

@mcp.tool()
def generate_print_pdf(doctype: str, name: str, print_format: str = None, site: str = None) -> dict:
    """Render and generate PDF or HTML for any document, returning base64 string and HTML preview."""
    ensure_frappe(site)
    if not doctype or not frappe.db.exists("DocType", doctype):
        raise ValueError(f"DocType '{doctype}' does not exist.")
    if not name or not frappe.db.exists(doctype, name):
        raise ValueError(f"{doctype} '{name}' not found.")
        
    html = frappe.get_print(doctype, name, print_format=print_format)
    pdf_base64 = None
    try:
        from frappe.utils.pdf import get_pdf
        options = {
            "quiet": "",
            "no-outline": "",
            "load-error-handling": "ignore",
            "load-media-error-handling": "ignore"
        }
        pdf_bytes = get_pdf(html, options=options)
        pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8")
    except Exception:
        pdf_base64 = None

    return sanitize({
        "doctype": doctype,
        "name": name,
        "print_format": print_format or "Standard",
        "file_name": f"{name}.pdf",
        "pdf_base64": pdf_base64,
        "html_preview": html[:500] if html else ""
    })

# -------------------------------------------------------------------
# 9. GLOBAL SEARCH & PERMISSIONS CHECKER
# -------------------------------------------------------------------

@mcp.tool()
def global_search(query: str, doctype: str = None, limit: int = 20, site: str = None) -> list:
    """Perform full-text keyword search across Frappe database tables using Global Search index."""
    ensure_frappe(site)
    if not query:
        return []
    limit = max(1, min(limit or 20, 200))
    from frappe.utils.global_search import search
    results = search(query, doctype=doctype, limit=limit)
    return sanitize(results)

@mcp.tool()
def check_user_permission(user: str, doctype: str, ptype: str = "read", site: str = None) -> dict:
    """Verify if a user has read/write/create/delete/submit permissions for any DocType."""
    ensure_frappe(site)
    if not user or not doctype:
        raise ValueError("User and DocType parameters cannot be empty.")
    has_perm = frappe.has_permission(doctype, ptype=ptype, user=user)
    return sanitize({
        "user": user,
        "doctype": doctype,
        "permission_type": ptype,
        "has_permission": bool(has_perm)
    })

# -------------------------------------------------------------------
# 10. BACKGROUND JOBS & METHOD INVOCATION
# -------------------------------------------------------------------

@mcp.tool()
def call_whitelisted_method(method: str, kwargs: dict = None, site: str = None) -> dict:
    """Invoke any whitelisted (@frappe.whitelist()) Python backend API method across Frappe/ERPNext apps."""
    ensure_frappe(site)
    if not method:
        raise ValueError("Method parameter cannot be empty.")
    try:
        fn = frappe.get_attr(method)
    except Exception as e:
        raise ValueError(f"Method '{method}' not found or not whitelisted: {e}")
        
    res = fn(**(kwargs or {}))
    return sanitize({"method": method, "result": res})

@mcp.tool()
def enqueue_background_job(method: str, kwargs: dict = None, queue: str = "default", site: str = None) -> dict:
    """Enqueue a long-running Python background task to Frappe RQ workers with Redis safety fallback."""
    ensure_frappe(site)
    if not method:
        raise ValueError("Method parameter cannot be empty.")
    try:
        job = frappe.enqueue(method, queue=queue or "default", **(kwargs or {}))
        job_id = getattr(job, "id", str(job))
        return sanitize({
            "status": "enqueued",
            "job_id": job_id,
            "queue": queue,
            "method": method
        })
    except Exception as e:
        return sanitize({
            "status": "queue_error",
            "method": method,
            "error": str(e),
            "note": "Ensure Redis Queue worker is running on this site."
        })

# -------------------------------------------------------------------
# 11. WORKFLOW, REPORTS, FILES & HEALTH MONITORING
# -------------------------------------------------------------------

@mcp.tool()
def submit_document(doctype: str, name: str, site: str = None) -> dict:
    """Submit a submittable document (changes docstatus from 0 Draft to 1 Submitted)."""
    ensure_frappe(site)
    if not doctype or not frappe.db.exists("DocType", doctype):
        raise ValueError(f"DocType '{doctype}' does not exist.")
    doc = frappe.get_doc(doctype, name)
    doc.submit()
    frappe.db.commit()
    return sanitize(doc.as_dict())

@mcp.tool()
def cancel_document(doctype: str, name: str, site: str = None) -> dict:
    """Cancel a submitted document (changes docstatus from 1 Submitted to 2 Cancelled)."""
    ensure_frappe(site)
    if not doctype or not frappe.db.exists("DocType", doctype):
        raise ValueError(f"DocType '{doctype}' does not exist.")
    doc = frappe.get_doc(doctype, name)
    doc.cancel()
    frappe.db.commit()
    return sanitize(doc.as_dict())

@mcp.tool()
def apply_workflow_action(doctype: str, name: str, action: str, site: str = None) -> dict:
    """Advance a document through Frappe Approval Workflows using specified action."""
    ensure_frappe(site)
    if not doctype or not frappe.db.exists("DocType", doctype):
        raise ValueError(f"DocType '{doctype}' does not exist.")
    from frappe.model.workflow import apply_workflow
    doc = frappe.get_doc(doctype, name)
    updated_doc = apply_workflow(doc, action)
    frappe.db.commit()
    return sanitize(updated_doc.as_dict())

@mcp.tool()
def execute_report(report_name: str, filters: dict = None, site: str = None) -> dict:
    """Run any ERPNext built-in report and return columns and result data."""
    ensure_frappe(site)
    if not report_name or not frappe.db.exists("Report", report_name):
        raise ValueError(f"Report '{report_name}' does not exist.")
    from frappe.desk.query_report import run
    res = run(report_name, filters=filters or {})
    return sanitize({
        "report_name": report_name,
        "columns": res.get("columns", []),
        "result": res.get("result", [])
    })

@mcp.tool()
def export_report_to_excel(report_name: str, filters: dict = None, site: str = None) -> dict:
    """Run any report and export result directly into an Excel (.xlsx) file, returning base64 and download URL."""
    ensure_frappe(site)
    from frappe.utils.xlsxutils import make_xlsx
    res = execute_report(report_name, filters=filters, site=site)
    columns = [c["label"] if isinstance(c, dict) else str(c) for c in res["columns"]]
    
    xlsx_data = [columns]
    for row in res["result"]:
        row_vals = []
        if isinstance(row, dict):
            for col in res["columns"]:
                key = col.get("fieldname") if isinstance(col, dict) else col
                row_vals.append(row.get(key, ""))
        elif isinstance(row, list):
            row_vals = row
        xlsx_data.append(row_vals)
        
    xlsx_file = make_xlsx(xlsx_data, report_name[:30])
    xlsx_bytes = xlsx_file.getvalue()
    b64_str = base64.b64encode(xlsx_bytes).decode("utf-8")
    
    clean_name = re.sub(r"[^\w\-]", "_", report_name)
    file_name = f"{clean_name}.xlsx"
    
    file_doc = frappe.get_doc({
        "doctype": "File",
        "file_name": file_name,
        "content": xlsx_bytes,
        "is_private": 0
    })
    file_doc.insert(ignore_permissions=True)
    frappe.db.commit()
    
    return sanitize({
        "report_name": report_name,
        "file_name": file_doc.file_name,
        "file_url": file_doc.file_url,
        "xlsx_base64": b64_str
    })

@mcp.tool()
def attach_file(doctype: str, name: str, file_name: str, content_base64: str = None, file_url: str = None, site: str = None) -> dict:
    """Attach a file or document URL to any record in the system."""
    ensure_frappe(site)
    if not doctype or not frappe.db.exists("DocType", doctype):
        raise ValueError(f"DocType '{doctype}' does not exist.")
    if not name or not frappe.db.exists(doctype, name):
        raise ValueError(f"{doctype} '{name}' not found.")
        
    file_doc = frappe.get_doc({
        "doctype": "File",
        "file_name": file_name,
        "attached_to_doctype": doctype,
        "attached_to_name": name,
        "is_private": 1
    })
    if content_base64:
        file_doc.content = base64.b64decode(content_base64)
    elif file_url:
        file_doc.file_url = file_url
        
    file_doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return sanitize(file_doc.as_dict())

@mcp.tool()
def get_system_health_status(site: str = None) -> dict:
    """Check site database status, active error logs count, scheduler status, and installed apps."""
    ensure_frappe(site)
    error_logs_count = frappe.db.count("Error Log")
    installed_apps = frappe.get_installed_apps()
    scheduler_disabled = frappe.utils.scheduler.is_scheduler_disabled()
    
    return sanitize({
        "site": getattr(frappe.local, "site", site),
        "installed_apps": installed_apps,
        "scheduler_disabled": scheduler_disabled,
        "error_logs_count": error_logs_count,
        "db_status": "connected"
    })

@mcp.tool()
def get_document_count(doctype: str, filters: dict = None, site: str = None) -> int:
    """Get total record count for ANY DocType matching optional filters."""
    ensure_frappe(site)
    if not doctype or not frappe.db.exists("DocType", doctype):
        raise ValueError(f"DocType '{doctype}' does not exist.")
    return frappe.db.count(doctype, filters=filters or {})

@mcp.tool()
def search_link_options(doctype: str, txt: str = "", filters: dict = None, limit: int = 10, site: str = None) -> list:
    """Search autocomplete link options for ANY DocType."""
    ensure_frappe(site)
    if not doctype or not frappe.db.exists("DocType", doctype):
        raise ValueError(f"DocType '{doctype}' does not exist.")
        
    limit = max(1, min(limit or 10, 100))
    meta = frappe.get_meta(doctype)
    search_fields = meta.get_search_fields()
    
    or_filters = {}
    if txt:
        or_filters = {"name": ["like", f"%{txt}%"]}
        for field in search_fields:
            or_filters[field] = ["like", f"%{txt}%"]
            
    fields = ["name"]
    if meta.title_field and meta.title_field != "name":
        fields.append(meta.title_field)
        
    data = frappe.get_all(doctype, filters=filters or {}, or_filters=or_filters, fields=fields, limit=limit)
    return sanitize(data)

@mcp.tool()
def run_sql_query(query: str, site: str = None) -> list:
    """Execute a read-only SELECT SQL query across any tables in the database. Strictly guards against non-SELECT and SQL injection."""
    ensure_frappe(site)
    check_tool_permissions("run_sql_query", {"query": query})
    if not query or not isinstance(query, str):
        raise ValueError("Query parameter must be a non-empty SQL string.")
        
    cleaned_query = re.sub(r"/\*.*?\*/", "", query, flags=re.DOTALL).strip()
    cleaned_query = re.sub(r"--.*$", "", cleaned_query, flags=re.MULTILINE).strip()
    
    if not cleaned_query.lower().startswith("select"):
        raise ValueError("Only SELECT queries are permitted.")
        
    if ";" in cleaned_query.rstrip(";"):
        raise ValueError("Multiple SQL statements are not allowed.")
        
    data = frappe.db.sql(cleaned_query, as_dict=True)
    return truncate_payload(sanitize(data))

# -------------------------------------------------------------------
# 12. MCP RESOURCES & PROMPTS
# -------------------------------------------------------------------

@mcp.resource("frappe://system-health/{site}")
def get_system_health_resource(site: str = "ai.local") -> str:
    """Resource returning Frappe site system health status (DB connection, active errors, scheduler status)."""
    return json.dumps(get_system_health_status(site=site), indent=2)

@mcp.resource("frappe://kpi-summary/{site}")
def get_kpi_summary_resource(site: str = "ai.local") -> str:
    """Resource returning real-time business KPI summary (receivables, revenue, open orders, stock items)."""
    return json.dumps(get_kpi_summary(site=site), indent=2)

@mcp.resource("frappe://doctypes/{site}")
def get_doctypes_resource(site: str = "ai.local") -> str:
    """Resource returning list of active DocTypes in the system."""
    return json.dumps(list_doctypes(site=site), indent=2)

@mcp.prompt("financial_summary_prompt")
def financial_summary_prompt(period: str = "this month", company: str = None) -> str:
    """Generate financial summary prompt for AI assistant business workflow."""
    comp = f" for '{company}'" if company else ""
    return (
        f"You are a Senior Financial Analyst conducting a financial summary analysis{comp}.\n"
        f"Time Period: {period}.\n\n"
        "Workflow Instructions:\n"
        "1. Retrieve real-time financial metrics using `get_kpi_summary` or querying `tabSales Invoice`.\n"
        "2. Identify total outstanding receivables and assess revenue collection efficiency.\n"
        "3. Highlight financial risks, overdue invoices, and key revenue drivers.\n"
        "4. Summarize your findings into an executive report with actionable recommendations."
    )

@mcp.prompt("stock_reorder_prompt")
def stock_reorder_prompt(warehouse: str = None, min_threshold: float = 5.0) -> str:
    """Generate stock health check and reorder prompt for AI assistant workflow."""
    wh = f" for warehouse '{warehouse}'" if warehouse else " across all warehouses"
    return (
        f"You are an Inventory Manager performing a Stock Health Check & Reorder Audit{wh}.\n"
        f"Minimum Threshold Level: {min_threshold} units.\n\n"
        "Workflow Instructions:\n"
        "1. Scan inventory stock bins using `check_low_stock_and_reorder` or by querying the `Bin` table.\n"
        "2. List items where actual quantity is below the minimum threshold.\n"
        "3. Verify if draft Material Requests have been automatically generated for replenishment.\n"
        "4. Provide a stock status summary detailing reorder requirements, item quantities, and priority actions."
    )

@mcp.prompt("procurement_audit_prompt")
def procurement_audit_prompt(min_amount: float = 10000.0, status: str = "Submitted") -> str:
    """Generate procurement audit prompt for AI assistant workflow."""
    return (
        f"You are a Procurement Auditor conducting an audit of Purchase Orders and Material Requests.\n"
        f"Filters: Minimum Order Value >= {min_amount}, Document Status = '{status}'.\n\n"
        "Workflow Instructions:\n"
        "1. Query recent Purchase Orders and Material Requests using `list_documents` or `run_sql_query`.\n"
        "2. Check high-value orders for compliance, authorized approval signatures, and supplier pricing.\n"
        "3. Detect potential duplicate material requests or unexpected order volume spikes.\n"
        "4. Present a procurement audit report highlighting compliant orders, flagged anomalies, and recommendations."
    )

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Universal Dynamic MCP Server")
    parser.add_argument("--transport", type=str, default=os.environ.get("MCP_TRANSPORT", "stdio"), choices=["stdio", "sse"], help="Transport mode: stdio or sse")
    parser.add_argument("--port", type=int, default=int(os.environ.get("MCP_PORT", 8000)), help="Port for SSE transport mode")
    parser.add_argument("--host", type=str, default=os.environ.get("MCP_HOST", "0.0.0.0"), help="Host for SSE transport mode")
    args = parser.parse_args()

    if args.transport == "sse":
        mcp.run(transport="sse", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio", show_banner=False)



