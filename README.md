# Vector Search RLS MCP Server

A custom [Model Context Protocol](https://modelcontextprotocol.io) server, deployed as a
[Databricks App](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/), that adds
**row-level security (RLS)** to a Databricks Vector Search index.

> Built from the Databricks
> [`mcp-server-hello-world`](https://github.com/databricks/app-templates/tree/main/mcp-server-hello-world)
> app template, then extended with the RLS-aware search tool and the data/index setup below.

## Why this exists

Databricks Vector Search has **no native row-level security** — access to an index is
all-or-nothing. The Databricks *managed* Vector Search MCP server inherits that limitation:
if a user can query an index, it returns **every** matching row regardless of who is asking.

This server is a **drop-in replacement** for the managed VS MCP tool (same tool name,
description, and single `query` argument) that transparently enforces RLS:

1. **Index-level gate** — the query runs *on behalf of the calling user* (their forwarded
   OAuth token), so Unity Catalog still governs who can touch the index at all.
2. **Row-level gate** — results are filtered to rows whose ACL column (`acl_email`) matches
   the caller's identity. This is the RLS layer Vector Search lacks.

Because the filter value comes from the platform-injected `x-forwarded-access-token` (not a
tool argument), a caller cannot spoof their way past it.

## How it works

```
Client (Copilot / Playground / agent)
        │  OAuth  ─ tool: <catalog>__<schema>__<index>(query)
        ▼
Databricks App (this MCP server, /mcp)
        │  get_user_authenticated_workspace_client()  ← x-forwarded-access-token (OBO)
        │  caller = current_user.me().user_name
        ▼
vector_search_indexes.query_index(
    query_text=query,
    filters_json={"acl_email": caller}   ← row-level security
)
```

## Tool schema

The server exposes one search tool. Its name is derived from the index (`VS_INDEX_NAME` with
dots replaced by `__`), e.g. `conrad_demo_catalog__vs_rls_demo__messages_index`.

**Input** (identical to the native VS MCP tool):

```json
{
  "type": "object",
  "required": ["query"],
  "properties": {
    "query": { "type": "string", "description": "The query string to search the vector index" }
  }
}
```

`num_results`, `columns`, and the RLS filter are server-side (env config / the caller's
identity), not caller arguments.

**Output** — a JSON array of matching rows, each returned column plus a relevance `score`:

```json
[
  {
    "id": "msg-0224",
    "sender": "dana.cole@example.com",
    "recipient": "conrad.ho@databricks.com",
    "subject": "Q1 budget review for the analytics team",
    "topic": "quarterly budget",
    "body": "Please find attached the analytics spend forecast ...",
    "acl_email": "conrad.ho@databricks.com",
    "score": 0.6514
  }
]
```

### How it differs from the native Vector Search MCP server

| Aspect | Native managed VS MCP tool | This server |
|---|---|---|
| Tool name | `<catalog>__<schema>__<index>` | identical |
| Input schema | `{ query: string }` | identical |
| Output shape | array of row objects + `score` | identical |
| Description | "A vector search-based retrieval tool …" | same, plus a note that RLS is applied |
| Rows returned | every matching row in the index | only rows where `acl_email` = caller |
| Net effect | results leak across users (no RLS) | row-level security enforced |

Same name, same input, same output shape — a client can repoint from the managed MCP URL to
this app's `/mcp` and call the exact same tool. The only behavioral change is that results are
scoped to the caller.

## Project structure

```
server/
├── app.py     # FastAPI + FastMCP wiring, header-capture middleware (do not edit middleware)
├── main.py    # uvicorn entry point (the `vector-search-rls` command)
├── tools.py   # the query_vector_index tool (RLS) + get_current_user
└── utils.py   # OBO auth helper (reads x-forwarded-access-token)
setup/
└── generate_emails.py   # re-runnable synthetic data generator (configurable owners)
app.yaml       # Databricks App run command + VS_* env config
```

## Configuration

The tool reads these from `app.yaml` `env` (overridable without code changes):

| Env var | Default | Meaning |
|---|---|---|
| `VS_INDEX_NAME` | `conrad_demo_catalog.vs_rls_demo.messages_index` | Index to query; also derives the tool name (dots → `__`) |
| `ACL_COLUMN` | `acl_email` | Column filtered against the caller's identity |
| `RETURN_COLUMNS` | `id,sender,recipient,subject,topic,body,acl_email` | Columns returned per row |
| `NUM_RESULTS` | `5` | Max rows returned |

## Setup (data + index)

The demo data and index live in Unity Catalog. To (re)build them:

```bash
# 1. Generate synthetic emails (edit OWNER_EMAILS in the script first)
python setup/generate_emails.py --out /tmp/emails.csv

# 2. Upload + load into a CDF-enabled Delta table, then create the Delta-Sync index
#    with Databricks-computed embeddings (databricks-gte-large-en) and acl_email as a
#    filterable column. Adapt the catalog.schema to your workspace.
```

Each owner in `OWNER_EMAILS` **must be a real Databricks identity** that will call the
agent (OBO) — otherwise their filtered searches return nothing.

### Why a Delta-Sync index with managed embeddings

- **Delta-Sync index** — the index stays automatically in sync with the source Delta table.
  When you re-run the generator (e.g. add an owner or change ACL assignments), the new rows —
  including the `acl_email` column the RLS filter depends on — flow into the index without any
  manual re-embedding or upserts. A Direct-Access index would make us manage vectors and CRUD
  ourselves; Delta-Sync keeps the table as the single source of truth.
- **Managed (Databricks-computed) embeddings** — Databricks embeds the `body` text with a
  Foundation Model endpoint (`databricks-gte-large-en`) at sync time, and embeds the incoming
  query at query time. So the tool just passes `query_text` (no client-side vectorization),
  and we don't host an embedding model or attach an embedding serving endpoint as an app
  resource. Self-managed embeddings would require computing and storing vectors ourselves.

## Run locally

```bash
./scripts/dev/start_server.sh        # serves http://localhost:8000/mcp
```
Locally, OBO falls back to your developer identity, so searches return *your* rows.

## Deploy

```bash
databricks sync . /Workspace/Users/<you>/vector-search-rls-demo --profile <profile>
databricks apps deploy vector-search-rls-demo \
  --source-code-path /Workspace/Users/<you>/vector-search-rls-demo --profile <profile>
```

The app must be configured with **user authorization** scopes
(`vectorsearch.vector-search-indexes`, `vectorsearch.vector-search-endpoints`,
`iam.current-user:read`) and the calling users need `USE CATALOG` / `USE SCHEMA` / `SELECT`
on the index.

## Test

```bash
# OAuth token (must be U2M; PATs are not accepted by MCP)
TOK=$(databricks auth token --profile <profile> | jq -r .access_token)

# Initialize handshake
curl -s -X POST "https://<app-url>/mcp" \
  -H "Authorization: Bearer $TOK" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1.0"}}}'
```

Or point **MCP Inspector** (`npx @modelcontextprotocol/inspector`) at `https://<app-url>/mcp`
with transport **Streamable HTTP** and the bearer token, or add the app as a tool in the
Databricks **AI Playground**.

**Proving RLS:** call the tool as two different users — each gets only their own rows,
whereas the native managed VS MCP tool returns everyone's.

## Troubleshooting

- **401 from the app** — the bearer token must be a workspace OAuth (U2M) token with app
  access. A broad token from `databricks auth token` works; a narrowly resource-scoped token
  is rejected at the ingress. PATs are not accepted by MCP.
- **Token expired** — tokens last ~1 hour. Re-mint with `databricks auth token`. MCP Inspector
  holds a static snapshot, so re-paste after re-minting.
- **MCP Inspector "proxy token" error** — that's Inspector's own local session token
  (`MCP_PROXY_AUTH_TOKEN`), separate from your Databricks token. Open Inspector via the
  console URL it prints (it includes the proxy token).
- **Search returns nothing** — the caller's identity has no rows whose `acl_email` matches it,
  or the caller lacks `SELECT` on the index. The OBO query scopes
  (`vectorsearch.vector-search-indexes`, `vectorsearch.vector-search-endpoints`) come from the
  app's configured user-authorization scopes, not the token you present.

## Integration tests

```bash
uv run pytest tests/
```
