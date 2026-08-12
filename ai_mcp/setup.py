from setuptools import setup, find_packages

setup(
    name="ai_mcp",
    version="0.0.1",
    description="Universal Dynamic MCP Server for Frappe / ERPNext",
    author="ERPNext AI Team",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=["fastmcp"]
)
