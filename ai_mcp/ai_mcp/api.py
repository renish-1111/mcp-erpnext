import time
import json
import frappe
from ai_mcp import mcp_server

@frappe.whitelist()
def execute_tool(tool_name: str, args: dict = None) -> dict:
    """
    Whitelisted HTTP REST API endpoint to execute any MCP tool in ai_mcp.
    Endpoint: /api/method/ai_mcp.api.execute_tool
    Parameters:
      - tool_name: Name of the MCP tool function (e.g. 'get_kpi_summary', 'list_documents', 'global_search')
      - args: Dictionary of arguments to pass to the tool
    """
    # Check if MCP server is enabled in settings
    if frappe.db.exists("DocType", "AI MCP Settings"):
        settings = frappe.get_single("AI MCP Settings")
        if not settings.get("enable_mcp_server"):
            frappe.throw("AI MCP Server is currently disabled in AI MCP Settings.", frappe.PermissionError)

    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            args = {}
            
    args = args or {}
    start_time = time.time()
    
    if not hasattr(mcp_server, tool_name):
        frappe.throw(f"MCP tool '{tool_name}' does not exist in ai_mcp.")
        
    fn = getattr(mcp_server, tool_name)
    
    try:
        # Check rate-limiting guardrail
        mcp_server.check_rate_limit()

        # Check role-based tool permission matrix
        mcp_server.check_tool_permissions(tool_name, args)

        result = fn(**args)
        
        # Truncate oversized response payload gracefully if exceeding max size limit (default 100KB)
        result = mcp_server.truncate_payload(result)

        latency = round((time.time() - start_time) * 1000, 2)
        mcp_server.log_mcp_action(tool_name, args, status="Success", result=result, execution_time_ms=latency)
        return {
            "status": "success",
            "tool_name": tool_name,
            "execution_time_ms": latency,
            "result": result
        }
    except Exception as e:
        latency = round((time.time() - start_time) * 1000, 2)
        error_msg = str(e)
        mcp_server.log_mcp_action(tool_name, args, status="Error", result={"error": error_msg}, execution_time_ms=latency)
        frappe.throw(f"Error executing MCP tool '{tool_name}': {error_msg}")

@frappe.whitelist()
def list_available_tools() -> list:
    """
    HTTP REST API endpoint to list all available tools in ai_mcp.
    Endpoint: /api/method/ai_mcp.api.list_available_tools
    """
    tools = []
    excluded = ["ensure_frappe", "sanitize", "log_mcp_action", "_write_mcp_audit_log", "run_sse_server", "check_rate_limit", "check_tool_permissions", "truncate_payload"]
    for attr_name in dir(mcp_server):
        attr = getattr(mcp_server, attr_name)
        if callable(attr) and getattr(attr, "__doc__", None) and not attr_name.startswith("_") and attr_name not in excluded:
            tools.append({
                "name": attr_name,
                "description": attr.__doc__.strip()
            })
    return tools

@frappe.whitelist()
def sse_endpoint(port: int = 8000, host: str = None) -> dict:
    """
    Whitelisted HTTP REST API endpoint providing Server-Sent Events (SSE) remote transport connection metadata and endpoint URLs.
    Endpoint: /api/method/ai_mcp.api.sse_endpoint
    """
    if frappe.db.exists("DocType", "AI MCP Settings"):
        settings = frappe.get_single("AI MCP Settings")
        if not settings.get("enable_mcp_server"):
            frappe.throw("AI MCP Server is currently disabled in AI MCP Settings.", frappe.PermissionError)

    site = getattr(frappe.local, "site", None) or "ai.local"
    if not host:
        request = getattr(frappe.local, "request", None)
        if request and getattr(request, "host", None):
            host = request.host.split(":")[0]
        else:
            host = "localhost"

    sse_url = f"http://{host}:{port}/sse"
    messages_url = f"http://{host}:{port}/messages"

    if getattr(frappe.local, "response", None) is not None:
        frappe.response["headers"] = {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }

    return {
        "status": "active",
        "transport": "sse",
        "site": site,
        "host": host,
        "port": port,
        "sse_url": sse_url,
        "messages_url": messages_url,
        "instructions": f"Connect remote MCP client using SSE streaming transport to {sse_url}"
    }

@frappe.whitelist()
def sse_stream(port: int = 8000) -> dict:
    """
    HTTP REST helper endpoint for SSE transport connection setup.
    Endpoint: /api/method/ai_mcp.api.sse_stream
    """
    return sse_endpoint(port=port)
