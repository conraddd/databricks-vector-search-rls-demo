"""
Tools module for the MCP server.

This module defines all the tools (functions) that the MCP server exposes to clients.
Tools are the core functionality of an MCP server - they are callable functions that
AI assistants and other clients can invoke to perform specific actions.

Each tool should:
- Have a clear, descriptive name
- Include comprehensive docstrings (used by AI to understand when to call the tool)
- Return structured data (typically dict or list)
- Handle errors gracefully
"""

import json
import os

from databricks.sdk.errors import NotFound, PermissionDenied
from fastmcp.exceptions import ToolError

from server import utils

# Vector Search RLS configuration (overridable via app.yaml env vars).
VS_INDEX_NAME = os.environ.get(
    "VS_INDEX_NAME", "conrad_demo_catalog.vs_rls_demo.messages_index"
)
ACL_COLUMN = os.environ.get("ACL_COLUMN", "acl_email")
RETURN_COLUMNS = [
    c.strip()
    for c in os.environ.get(
        "RETURN_COLUMNS", "id,sender,recipient,subject,topic,body,acl_email"
    ).split(",")
    if c.strip()
]
NUM_RESULTS = int(os.environ.get("NUM_RESULTS", "5"))

# Mirror the native Databricks-managed Vector Search MCP server's tool name and
# description so this custom server is a drop-in replacement. The native server
# names the tool after the fully qualified index name with dots replaced by "__"
# and takes a single `query` argument; num_results/columns/filters are
# server-side config (here, the filter is injected from the caller's identity).
TOOL_NAME = VS_INDEX_NAME.replace(".", "__")
TOOL_DESCRIPTION = (
    "A vector search-based retrieval tool for querying indexed embeddings "
    f"using vector index {VS_INDEX_NAME}. "
    "Row-level security is enforced: results are automatically filtered to only "
    "the rows the calling user is authorized to see, based on their identity."
)


def load_tools(mcp_server):
    """
    Register all MCP tools with the server.

    This function is called during server initialization to register all available
    tools with the MCP server instance. Tools are registered using the @mcp_server.tool
    decorator, which makes them available to clients via the MCP protocol.

    Args:
        mcp_server: The FastMCP server instance to register tools with. This is the
                   main server object that handles tool registration and routing.

    Example:
        To add a new tool, define it within this function using the decorator:

        @mcp_server.tool
        def my_new_tool(param: str) -> dict:
            '''Description of what the tool does.'''
            return {"result": f"Processed {param}"}
    """

    @mcp_server.tool
    def get_current_user() -> dict:
        """
        Get information about the current authenticated user.

        This tool retrieves details about the user who is currently authenticated
        with the MCP server. When deployed as a Databricks App, this returns
        information about the end user making the request. When running locally,
        it returns information about the developer's Databricks identity.

        Useful for:
        - Personalizing responses based on the user
        - Authorization checks
        - Audit logging
        - User-specific operations

        Returns:
            dict: A dictionary containing:
                - display_name (str): The user's display name
                - user_name (str): The user's username/email
                - active (bool): Whether the user account is active

        Example response:
            {
                "display_name": "John Doe",
                "user_name": "john.doe@example.com",
                "active": true
            }

        Raises:
            Returns error dict if authentication fails or user info cannot be retrieved.
        """
        try:
            w = utils.get_user_authenticated_workspace_client()
            user = w.current_user.me()
            return {
                "display_name": user.display_name,
                "user_name": user.user_name,
                "active": user.active,
            }
        except Exception as e:
            return {"error": str(e), "message": "Failed to retrieve user information"}

    @mcp_server.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)
    def query_vector_index(query: str) -> list[dict]:
        """
        Query the Vector Search index with row-level security (RLS).

        Drop-in replacement for the native Databricks Vector Search MCP tool:
        same tool name, description, and single `query` argument. The difference
        is RLS, enforced two ways:
          1. The query runs on-behalf-of the calling user (their forwarded OAuth
             token), so Unity Catalog gates access to the index itself.
          2. Results are filtered to rows whose ACL column equals the caller's
             identity -- the row-level security, since Databricks Vector Search
             has no native RLS. num_results/columns are server-side config.

        Args:
            query: The query string to search the vector index.

        Returns:
            A list of matching rows (column name -> value, plus a relevance
            "score"), matching the native VS MCP server's output shape.
        """
        # Resolve the caller from their forwarded OAuth token (OBO). A missing
        # token raises ValueError in utils; we let it surface as a tool error
        # rather than masking it.
        w = utils.get_user_authenticated_workspace_client()
        caller = w.current_user.me().user_name

        # Row-level security: restrict results to rows owned by the caller.
        filters = {ACL_COLUMN: caller}

        try:
            resp = w.vector_search_indexes.query_index(
                index_name=VS_INDEX_NAME,
                columns=RETURN_COLUMNS,
                query_text=query,
                num_results=NUM_RESULTS,
                filters_json=json.dumps(filters),
            )
        except PermissionDenied as e:
            # Caller lacks UC access to the index (the index-level gate).
            raise ToolError(
                f"{caller} is not authorized to query index {VS_INDEX_NAME}."
            ) from e
        except NotFound as e:
            raise ToolError(f"Vector Search index {VS_INDEX_NAME} was not found.") from e

        # Match the native VS MCP server's output: a list of row objects
        # (column name -> value, plus a relevance "score").
        cols = [c.name for c in (resp.manifest.columns if resp.manifest else [])]
        data = (resp.result.data_array if resp.result else None) or []
        return [dict(zip(cols, row)) for row in data]
