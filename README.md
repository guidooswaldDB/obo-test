# Databricks OBO Authentication Test App

A Streamlit application deployed as a Databricks App that demonstrates **On-Behalf-Of (OBO) user authentication**. The app executes all API calls using the logged-in user's identity, ensuring Unity Catalog permissions (row/column filters, ACLs) are enforced per user.

## Features

- Displays the authenticated user's identity (username, display name, ID, groups)
- Shows the workspace host and OBO token scopes for debugging
- Queries any Unity Catalog table via the SQL Statement API using the user's OBO token
- Deployable as a Databricks Asset Bundle (DAB) with environment-specific targets

## Project Structure

```
obo_test/
├── databricks.yml              # DAB configuration (bundle name, targets)
├── resources/
│   └── obo_test.app.yml        # App resource definition (name, scopes, permissions)
├── src/
│   └── app/
│       ├── app.py              # Streamlit application
│       ├── app.yaml            # App runtime config (command, env vars)
│       └── requirements.txt    # Python dependencies
├── .gitignore
└── README.md
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      User's Browser                         │
│                                                             │
│  1. User navigates to the Databricks App URL                │
│  2. Databricks OAuth flow authenticates the user            │
│  3. Databricks proxy injects x-forwarded-access-token       │
│     header with the user's OBO token                        │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              Databricks Apps Runtime                        │
│              (Python 3.11, 2 vCPU, 6 GB RAM)               │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │               Streamlit App (app.py)                  │  │
│  │                                                       │  │
│  │  ┌─────────────────┐    ┌──────────────────────────┐  │  │
│  │  │  OBO Token       │    │  Environment Variables   │  │  │
│  │  │  Extraction      │    │                          │  │  │
│  │  │                  │    │  DATABRICKS_HOST         │  │  │
│  │  │  x-forwarded-    │    │  DATABRICKS_WAREHOUSE_ID │  │  │
│  │  │  access-token    │    │  DATABRICKS_CLIENT_ID *  │  │  │
│  │  │  header          │    │  DATABRICKS_CLIENT_SECRET*│  │  │
│  │  └────────┬─────────┘    └──────────────────────────┘  │  │
│  │           │                                            │  │
│  │           │  Bearer token                              │  │
│  │           ▼                                            │  │
│  │  ┌─────────────────────────────────────────────────┐   │  │
│  │  │          REST API Calls (requests)              │   │  │
│  │  │                                                 │   │  │
│  │  │  GET  /api/2.0/preview/scim/v2/Me              │   │  │
│  │  │       → User identity (name, groups, ID)       │   │  │
│  │  │                                                 │   │  │
│  │  │  POST /api/2.0/sql/statements                  │   │  │
│  │  │       → Execute SQL as the logged-in user      │   │  │
│  │  │                                                 │   │  │
│  │  │  GET  /api/2.0/sql/statements/{id}             │   │  │
│  │  │       → Poll for query completion              │   │  │
│  │  └─────────────────────────────────────────────────┘   │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  * SP credentials are auto-injected but NOT used by this    │
│    app. All calls use the OBO user token exclusively.       │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                 Databricks Workspace                        │
│                                                             │
│  ┌──────────────┐    ┌──────────────────────────────────┐   │
│  │  SCIM API    │    │  SQL Statement API               │   │
│  │              │    │                                  │   │
│  │  /Me         │    │  Executes queries on a SQL       │   │
│  │  endpoint    │    │  Warehouse using the user's      │   │
│  │              │    │  identity and permissions         │   │
│  └──────────────┘    └───────────────┬──────────────────┘   │
│                                      │                      │
│                                      ▼                      │
│                      ┌──────────────────────────────────┐   │
│                      │  SQL Warehouse                   │   │
│                      │                                  │   │
│                      │  Unity Catalog enforces:         │   │
│                      │  - Table ACLs                    │   │
│                      │  - Row/column filters            │   │
│                      │  - Data masking                  │   │
│                      └──────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Authentication Flow

1. **User visits the app URL** — Databricks triggers an OAuth consent flow
2. **Databricks proxy** authenticates the user and injects the `x-forwarded-access-token` HTTP header containing the user's OBO JWT
3. **Streamlit app** reads the token from `st.context.headers` and uses it as a Bearer token for all REST API calls
4. **No SDK used** — the app deliberately avoids the Databricks SDK (`WorkspaceClient`, `Config`) because the auto-injected service principal environment variables (`DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET`) conflict with the OBO token, causing auth validation errors. All API calls use plain `requests` with the OBO Bearer token.

### Why Plain REST Instead of the SDK

The Databricks Apps runtime injects service principal OAuth credentials (`DATABRICKS_CLIENT_ID`/`DATABRICKS_CLIENT_SECRET`) as environment variables. Both the Databricks SDK (`WorkspaceClient`) and the SQL connector (`databricks-sql-connector`) auto-detect these and refuse to accept an additional `access_token` or `token` parameter, raising:

```
ValueError: more than one authorization method configured: oauth and pat
```

Using `requests` directly with the OBO Bearer token bypasses this entirely.

## Libraries

| Library | Version | Purpose |
|---------|---------|---------|
| **streamlit** | 1.38.0 (pre-installed) | Web UI framework |
| **requests** | (pre-installed) | HTTP client for Databricks REST APIs |
| **databricks-sql-connector** | (in requirements.txt) | Not actively used; kept as a dependency |

**Standard library modules used:** `os`, `time`, `base64`, `json`

## OAuth Scopes

Configured in the DAB resource file (`resources/obo_test.app.yml`):

| Scope | Purpose |
|-------|---------|
| `sql` | Execute SQL queries via the Statement API |
| `iam.current-user:read` | Read current user identity (included by default) |
| `iam.access-control:read` | Read access control info (included by default) |

## Prerequisites

1. **Workspace admin must enable user authorization** (Public Preview feature)
2. A **SQL Warehouse** accessible to app users
3. **Databricks CLI** installed and configured with a profile

## Deployment

```bash
# Validate the bundle
databricks bundle validate -t dev --profile <your-profile>

# Deploy
databricks bundle deploy -t dev --profile <your-profile>

# Start the app
databricks bundle run obo_test -t dev --profile <your-profile>
```

### Post-Deployment

1. Add a **SQL Warehouse** resource to the app via the Databricks UI (referenced by `valueFrom: sql-warehouse` in `app.yaml`)
2. Verify **user authorization** is enabled and the `sql` scope appears in the app settings
3. Open the app URL in an **incognito window** to ensure a fresh OAuth token with all scopes

## Configuration

### DAB Targets

| Target | Mode | Description |
|--------|------|-------------|
| `dev` | development | Default target for development |

Add additional targets (staging, prod) in `databricks.yml` as needed.

### Environment Variables

| Variable | Source | Description |
|----------|--------|-------------|
| `DATABRICKS_HOST` | Auto-injected | Workspace URL |
| `DATABRICKS_WAREHOUSE_ID` | `valueFrom: sql-warehouse` | Default SQL Warehouse ID |
| `DATABRICKS_CLIENT_ID` | Auto-injected | SP client ID (not used by this app) |
| `DATABRICKS_CLIENT_SECRET` | Auto-injected | SP client secret (not used by this app) |
