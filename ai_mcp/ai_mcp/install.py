import frappe

def after_install():
    """Executed automatically after `bench install-app ai_mcp` on any site."""
    init_settings()

def after_migrate():
    """Executed automatically after `bench migrate` on any site."""
    init_settings()

def init_settings():
    """Initialize default configuration for AI MCP Settings on the current site."""
    try:
        if frappe.db.exists("DocType", "AI MCP Settings"):
            settings = frappe.get_single("AI MCP Settings")
            settings.enable_mcp_server = 1
            settings.audit_log_mcp_actions = 1
            settings.max_query_limit = 100
            settings.auto_prefix_custom_fields = 1
            settings.enable_rate_limiting = 1
            settings.max_requests_per_minute = 60
            settings.max_payload_size_kb = 100
            settings.restrict_high_risk_tools = 1
            settings.save(ignore_permissions=True)
            frappe.db.commit()
    except Exception as e:
        frappe.log_error(f"Failed to initialize AI MCP Settings: {e}", "AI MCP Install Hook")
