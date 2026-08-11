app_name = "ai_mcp"
app_title = "AI MCP"
app_publisher = "ERPNext AI Team"
app_description = "Universal Dynamic MCP Server for Frappe / ERPNext"
app_email = "admin@ai.local"
app_license = "mit"

# Installation & Migration Hooks
after_install = "ai_mcp.install.after_install"
after_migrate = "ai_mcp.install.after_migrate"

# Bench Command Integration
commands = [
    "ai_mcp.commands.commands"
]

# Fixtures for seamless export/import across sites
fixtures = [
    "AI MCP Settings",
    {"dt": "Custom Field", "filters": [["module", "=", "AI MCP"]]},
    {"dt": "Property Setter", "filters": [["module", "=", "AI MCP"]]},
    {"dt": "Workspace", "filters": [["module", "=", "AI MCP"]]}
]

# Real-Time Event Webhook Hooks
doc_events = {
    "Purchase Order": {
        "on_submit": "ai_mcp.webhooks.on_purchase_order_submit"
    },
    "Material Request": {
        "on_submit": "ai_mcp.webhooks.on_material_request_submit"
    }
}

