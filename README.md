# 🤖 AI MCP - Universal Dynamic MCP Server for Frappe & ERPNext v16

`ai_mcp` is a native Frappe application that packages an enterprise-grade dynamic **Model Context Protocol (MCP)** server for Frappe and ERPNext v16. It exposes **36 dynamic tools**, FastMCP **Resources**, pre-built **Prompts**, Server-Sent Events (**SSE**) transport, and real-time **Document Event Webhooks** across all **816+ system DocTypes**.

---

## 🌟 Enterprise Features

1. **Single-Site & Multi-Site Single Install**
   - Seamlessly installs on any Frappe site with standard `bench install-app ai_mcp`. Auto-initializes `AI MCP Settings` and exports fixtures out of the box.
2. **Built-in Bench CLI Command**
   - Run the server for any site directly via `bench --site <site-name> mcp-server --transport [stdio|sse]`.
3. **816+ DocTypes Dynamic Operations**
   - Query, fetch, create, update, bulk-update, and delete documents dynamically across all modules (*Accounts, Stock, Selling, Buying, Manufacturing, Projects, Custom*).
4. **Role-Based Tool Permission Matrix**
   - Restricts high-risk tools (`run_sql_query`, `delete_document`, `create_custom_field`, `bulk_update_documents`) to `System Manager` or `AI Admin` roles or explicit `frappe.has_permission()` checks.
5. **Rate-Limiting & Payload Truncation Guardrails**
   - Redis-backed rate limiting (default 60 req/min) and automatic response payload truncation (default 100KB limit).
6. **Asynchronous Non-Blocking Audit Logging**
   - Offloads audit logging to background queues (`frappe.enqueue`) to eliminate DB write overhead during tool execution.
7. **FastMCP Resources & Prompts**
   - Dynamic resources (`frappe://system-health/{site}`, `frappe://kpi-summary/{site}`, `frappe://doctypes/{site}`) and AI business prompts (`financial_summary_prompt`, `stock_reorder_prompt`, `procurement_audit_prompt`).
8. **Real-Time Document Webhooks**
   - Document event triggers (`Purchase Order`, `Material Request`) sending real-time webhooks to AI agents upon document submission.

---

## 🚀 Installation & Setup

### 1. Install App on Any Site
```bash
cd ~/frappe-bench
bench get-app ai_mcp # or local path / git repository
bench --site site1.local install-app ai_mcp
```

### 2. Launch MCP Server for Any Site

#### Stdio Mode:
```bash
bench --site site1.local mcp-server
```

#### SSE Streaming Mode:
```bash
bench --site site1.local mcp-server --transport sse --port 8000
```

---

## 🌐 REST API & SSE Endpoints

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/method/ai_mcp.api.execute_tool` | `POST` | Execute any MCP tool over HTTP REST API. |
| `/api/method/ai_mcp.api.list_available_tools` | `GET` | List available tools and docstrings. |
| `/api/method/ai_mcp.api.sse_endpoint` | `GET/POST` | Get SSE connection URLs and streaming headers. |

---

## 🛠️ Complete MCP Tools Reference (36 Tools)

| Tool Category | Function Name | Description |
| :--- | :--- | :--- |
| **Discovery & Schema** | `list_doctypes` | List active DocTypes filtered by module or search keyword. |
| | `get_doctype_meta` | Fetch complete schema definition, fieldtypes, and child tables. |
| | `get_doctype_relations` | Map incoming/outgoing Link fields and child tables (ER-diagram). |
| **Schema Building** | `create_custom_field` | Create custom field dynamically with `custom_` prefix (Restricted). |
| | `add_property_setter` | Adjust standard field properties without editing core files. |
| **Universal CRUD** | `list_documents` | Query & list documents for any DocType with filters/sorting. |
| | `get_document` | Fetch full record details for any document. |
| | `create_document` | Insert new document record for any DocType. |
| | `update_document` | Update fields on existing record. |
| | `bulk_update_documents` | Bulk update multiple records in a single transaction (Restricted). |
| | `delete_document` | Delete record for any DocType (Restricted). |
| | `import_csv_data` | Parse & import base64-encoded CSV dataset. |
| **Automation Bots** | `check_low_stock_and_reorder` | Scan low stock items and auto-create draft Material Requests. |
| | `diagnose_and_clean_errors` | Group Error Logs by method and optionally purge old logs. |
| | `find_duplicate_records` | Detect duplicate column values for any DocType safely. |
| | `auto_approve_workflow` | Auto-apply 'Approve' action on Workflow-enabled documents. |
| **KPIs & Finance** | `get_kpi_summary` | Compute receivables, monthly sales, pending orders, item count. |
| | `get_currency_exchange_rate` | Get live/historical exchange rate between currencies. |
| **Communications** | `send_email_notification` | Send email via queue or log to Communication DocType. |
| | `attach_file` | Attach base64 file or URL to any document record. |
| **Transactions** | `commit_transaction` | Commit current DB transaction. |
| | `rollback_transaction` | Roll back current DB transaction. |
| **PDF & Printing** | `generate_print_pdf` | Render PDF/HTML preview for any document record. |
| **Search & Auth** | `global_search` | Keyword search across global index. |
| | `check_user_permission` | Check user read/write/create/delete permissions. |
| | `search_link_options` | Autocomplete options for Link fields. |
| **Methods & Background**| `call_whitelisted_method` | Execute any `@frappe.whitelist()` backend method. |
| | `enqueue_background_job` | Enqueue background job to RQ workers with Redis fallback. |
| **Lifecycle & Reports** | `submit_document` | Submit submittable document (docstatus 0 ➔ 1). |
| | `cancel_document` | Cancel submitted document (docstatus 1 ➔ 2). |
| | `apply_workflow_action` | Advance document state via Workflow action. |
| | `execute_report` | Run built-in Frappe/ERPNext report. |
| | `export_report_to_excel` | Export report directly to Excel (.xlsx) file. |
| | `get_system_health_status` | Check DB status, error logs, installed apps, scheduler. |
| | `get_document_count` | Get total record count for any DocType. |
| | `run_sql_query` | Read-only SQL SELECT queries with injection guardrails (Restricted). |
# mcp-erpnext
