import click
import frappe

@click.command("mcp-server")
@click.option("--site", help="Site name to run MCP server for", required=False)
@click.option("--transport", help="Transport mode: stdio or sse", default="stdio")
@click.option("--port", help="Port for SSE mode", type=int, default=8000)
@click.option("--host", help="Host address for SSE mode", default="0.0.0.0")
def mcp_server(site=None, transport="stdio", port=8000, host="0.0.0.0"):
    """Run Universal Dynamic MCP Server for Frappe/ERPNext site."""
    from ai_mcp.mcp_server import mcp, ensure_frappe, get_active_site
    site = site or getattr(frappe.local, "site", None) or get_active_site()
    ensure_frappe(site)
    click.echo(f"Starting AI MCP Server ({transport}) for site: {site}", err=True)
    if transport == "sse":
        click.echo(f"Running SSE streaming transport on {host}:{port}...", err=True)
        mcp.run(transport="sse", host=host, port=port)
    else:
        mcp.run(transport="stdio", show_banner=False)


commands = [mcp_server]

