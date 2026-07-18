# Deploying the Vector Search RLS MCP Server in Your Workspace

A step-by-step guide to running this row-level-security (RLS) MCP server in your own
Databricks workspace, written for someone new to Vector Search and MCP.

## What you're setting up (30-second overview)

- **A Vector Search index** = your searchable store of embeddings + metadata.
- **An MCP server** = a small app that exposes a "search" tool to AI clients (GitHub
  Copilot, Claude, Cursor, the Databricks AI Playground).
- This server adds **row-level security**: each user only sees the rows they're allowed
  to. It does this by running the search *as the calling user* and filtering results to
  rows whose **ACL column** matches that user's identity.
- The server runs as a **Databricks App**; AI clients connect to its `/mcp` URL over OAuth.

## Prerequisites

- A Databricks workspace with **Unity Catalog** and **Vector Search** enabled.
- Permission to **create Databricks Apps** and to **read your Vector Search index**.
- The repo's **GitHub URL** (and, if the repo is private, a GitHub token to clone it).
- (Optional) the **Databricks CLI** installed and logged in (`databricks auth login`).

---

## Step 1 — Build your data as a managed-embedding Delta-Sync index

> **Why this approach?** A *direct-access* index stores pre-computed vectors and needs the
> original embedding model to embed new search queries. If you don't have access to that
> model, rebuild your data as a **Delta-Sync index with managed embeddings**: Databricks
> embeds both your documents and incoming queries with its own model, so you need no
> external model and **no code changes**. (If you must keep a direct-access index, see the
> Appendix.)
>
> **Requirement:** you need the **source text** that was embedded (your documents), not
> just the vectors.

**1a. Land your text + an ACL column into a Delta table**

The table must contain:
- a **primary key** column (e.g. `id`),
- the **text** column you want searchable (e.g. `body` or `content`),
- an **ACL column** identifying who may see each row (e.g. `acl_email` holding a user's
  email, or `acl_group` for a group),
- any other columns you want search results to return.

Recover the data from your existing direct-access index by reading it back out with the
**scan** operation — no original embedding model required, because you're extracting stored
fields, not running a search.

- Collect the text and ACL columns using the Python SDK [scan_index](https://databricks-sdk-py.readthedocs.io/en/latest/workspace/vectorsearch/vector_search_indexes.html#databricks.sdk.service.vectorsearch.VectorSearchIndexesAPI.scan_index) ,ethod.
- Keep the primary key, text, and ACL columns (drop the vectors) and write them to a Delta
  table.

**1b. Enable Change Data Feed (required for Delta-Sync)**
- Turn on the `delta.enableChangeDataFeed` table property — set it with an
  `ALTER TABLE … SET TBLPROPERTIES` statement in the SQL Editor.

**1c. Create (or pick) a Vector Search endpoint — UI**
- Left sidebar → **Compute** → **Vector Search** tab → **Create endpoint**.
- Give it a name, type **Standard** → **Confirm**. Wait until it shows **Online**
  (a few minutes).

**1d. Create the Delta-Sync index from your table — UI**
- Left sidebar → **Catalog** → browse to your table.
- Top-right **Create** menu → **Vector search index**.
- In the dialog:
  - **Name**: e.g. `your_catalog.your_schema.your_index`
  - **Primary key**: your `id` column
  - **Endpoint**: the one from 1c
  - **Embedding source**: choose **"Compute embeddings"** (managed) →
    **Source column** = your text column →
    **Embedding model** = `databricks-gte-large-en` (Databricks-hosted; no special access)
  - **Sync mode**: **Triggered** (cheapest) or **Continuous** (auto-updates)
  - **Columns to sync / include**: make sure your **ACL column** is included so it's
    filterable
  - **Create** → wait until the index shows **Online** and rows are indexed.

**1e. Write down for later**: the **index name**, the **ACL column** name, and the
**columns** you want returned.

---

## Step 2 — Clone the repo into your Databricks workspace

- In Databricks, left sidebar → **Workspace** → navigate to your user folder.
- Click **Create** (top right) → **Git folder**.
- Paste the repo's **GitHub URL**, branch **main** → **Create Git folder**.
- This clones the code into your workspace, where you'll edit and deploy it.
- If the repo is **private** and you're prompted for credentials: go to your avatar →
  **Settings → Linked accounts** (Git integration) → add a GitHub **personal access
  token** first. **Public repos don't need this.**

---

## Step 3 — Point the app at your index (edit `app.yaml`)

- In the cloned Git folder, open **`app.yaml`** and edit the `env` values to match Step 1:
  - `VS_INDEX_NAME` → `your_catalog.your_schema.your_index`
  - `ACL_COLUMN` → your owner column, e.g. `acl_email`
  - `RETURN_COLUMNS` → comma-separated columns to return (include the text + ACL column)
  - `NUM_RESULTS` → e.g. `5`
- Save the file — you can edit it directly in the workspace; no commit/push is required to
  deploy.

---

## Step 4 — No code change needed ✅

Because your index uses **managed embeddings**, the built-in `query_vector_index` tool
works as-is: it searches with text, and Databricks embeds the query for you. Nothing to
edit in `server/tools.py`. (Only the Appendix's direct-access path requires a code change.)

---

## Step 5 — Create the Databricks App (UI — be precise here)

- Left sidebar → **Compute** → **Apps** tab → **Create app**.
- **Name: it should start with `mcp-`** (e.g. `mcp-vector-search-rls`). This is what makes it
  appear under **AI Gateway → MCPs**.
- Choose **Custom** (you'll deploy your own code), then configure:
  - **User authorization** → **+ Add scope** and add:
    - `vectorsearch.vector-search-indexes`
    - `vectorsearch.vector-search-endpoints`
  - **App resources**: not required for the managed-embedding path.
- Click **Create** and wait until the app shows **Running**.

---

## Step 6 — Deploy your code to the app (UI)

- Open your new app → click **Deploy** (or **Edit / Deploy source code**).
- For **Source code path**, choose the **Git folder** from Step 2.
- Click **Deploy** and wait for **"App started successfully."**

---

## Step 7 — Grant index access (Unity Catalog)

The people who will use the agent need permission to query the index. Grant each user (in
the **SQL Editor** with `GRANT` statements, or via the **Catalog Explorer** permissions UI):
- `USE CATALOG` on the catalog
- `USE SCHEMA` on the schema
- `SELECT` on the index

Also make sure each row's **ACL column value matches the email** of the user who should see
it.

---

## Step 8 — Test the MCP server in the Databricks AI Playground

The AI Playground is built into Databricks, so you can test without any third-party AI tool
or license.

- Left sidebar → **Playground** (under the **AI/ML** section), or search for "Playground".
- Select a model that supports **tools** (shown with a tool-enabled label).
- Click **Tools** → **+ Add tool** → choose **MCP servers** (or **Hosted MCP**) → select
  your `mcp-vector-search-rls` app from the list.
  - If it doesn't appear, confirm the app name starts with `mcp-` and the app is **Running**.
- Start chatting — the model will call your tool. The Playground calls the server as **you**
  (the signed-in user), so results are filtered to your identity automatically.

> Later, when you do have a third-party client (Claude Desktop / Copilot / Cursor), connect
> it to the app's `/mcp` URL using **Streamable HTTP** transport and an **OAuth** login —
> same server, no changes needed.

---

## Step 9 — Verify RLS works

- In the Playground, ask: **"Search for [a topic in your data] and list who each result
  belongs to."**
- Confirm every result's owner = **you** (the caller). Have a second user try in their own
  Playground session — they should get a **different** set.
- To show the contrast, also add the **managed** Vector Search MCP server as a tool (in
  **+ Add tool**, it appears as the schema's index under managed/AI Search) and run the
  same query — it returns **everyone's** rows, while this server returns only the caller's.

---

## Troubleshooting

- **401 when connecting** — the token expired or is wrong. Re-mint with
  `databricks auth token` and re-paste. Personal access tokens (PATs) are **not** accepted
  by MCP; use OAuth.
- **Empty results** — the caller's email doesn't match any row's ACL column, or they lack
  `SELECT` on the index.
- **App not in the MCPs tab** — the app name must start with `mcp-`.
- **MCP Inspector "proxy token" error** — that's Inspector's own local session token, not
  your Databricks token. Open Inspector via the console URL it prints.
- See the repo's **README → Troubleshooting** for more.

---

## Appendix — Keeping a direct-access index (advanced)

Use this only if you **cannot** rebuild from source text and must query your existing
direct-access index. A direct-access index has no managed embedding model, so you must
embed the query yourself with the **same model that produced your stored vectors**. In
**`server/tools.py`**, inside `query_vector_index`:

- Embed the incoming query with the same model your stored vectors used — call the model
  via the SDK `w.serving_endpoints.query` (for a Databricks serving endpoint) or your
  external embedding API.
- Pass that vector to `query_index` using the `query_vector` argument instead of
  `query_text`. The RLS filter (`filters_json`) stays exactly the same.
- If the embedding model is a **Databricks serving endpoint**, add it as an **App resource**
  (Step 5) with **Can query** permission.
- The query embedding **must use the same model** as your stored vectors, or results will
  be meaningless.
