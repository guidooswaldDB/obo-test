import os
import time

import requests
import streamlit as st

APP_VERSION = "v0.1.15"

st.set_page_config(page_title="OBO Auth Test", layout="wide")
st.title(f"Databricks OBO Authentication Test  `{APP_VERSION}`")

# --- Auth ---
user_token = st.context.headers.get("x-forwarded-access-token")

if not user_token:
    st.warning(
        "No user token found (`x-forwarded-access-token` header missing). "
        "This app must be deployed on Databricks with user authorization enabled. "
        "Make sure the app has the `sql` scope configured under User Authorization."
    )
    st.stop()

host = os.environ["DATABRICKS_HOST"]
if not host.startswith("https://"):
    host = f"https://{host}"
headers = {"Authorization": f"Bearer {user_token}"}

# Decode token to show scopes (JWT is base64, no verification needed for display)
try:
    import base64, json as _json
    payload = user_token.split(".")[1]
    payload += "=" * (-len(payload) % 4)  # pad base64
    token_claims = _json.loads(base64.urlsafe_b64decode(payload))
    token_scopes = token_claims.get("scp", token_claims.get("scope", "N/A"))
except Exception:
    token_scopes = "unable to decode"

# --- User & Workspace Info ---
st.header("Logged-in User")
try:
    resp = requests.get(
        f"{host}/api/2.0/preview/scim/v2/Me",
        headers=headers,
    )
    resp.raise_for_status()
    me = resp.json()
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Username", me.get("userName", "N/A"))
        st.metric("Display Name", me.get("displayName", "N/A"))
    with col2:
        st.metric("User ID", me.get("id", "N/A"))
        groups = ", ".join(g.get("display", "") for g in me.get("groups", []) if g.get("display")) or "N/A"
        st.metric("Groups", groups[:60] + ("..." if len(groups) > 60 else ""))
except Exception as e:
    st.error(f"Failed to fetch user info: {e}")
    st.stop()

st.header("Workspace")
st.metric("Host", host)

st.header("OBO Token")
st.metric("Scopes", str(token_scopes))

st.divider()

# --- Query Section ---
st.header("Query Table")

default_wh_id = os.getenv("DATABRICKS_WAREHOUSE_ID", "")
warehouse_id = st.text_input("SQL Warehouse ID", value=default_wh_id)
table_name = st.text_input("Full table name", placeholder="catalog.schema.table")


def run_sql(query: str) -> list[dict]:
    """Execute SQL via the Statement API using the OBO user token."""
    resp = requests.post(
        f"{host}/api/2.0/sql/statements",
        headers=headers,
        json={
            "warehouse_id": warehouse_id,
            "statement": query,
            "wait_timeout": "30s",
            "disposition": "INLINE",
        },
    )
    resp.raise_for_status()
    result = resp.json()

    while result.get("status", {}).get("state") in ("PENDING", "RUNNING"):
        time.sleep(1)
        stmt_id = result["statement_id"]
        poll = requests.get(f"{host}/api/2.0/sql/statements/{stmt_id}", headers=headers)
        poll.raise_for_status()
        result = poll.json()

    status = result.get("status", {})
    if status.get("state") != "SUCCEEDED":
        error = status.get("error", {}).get("message", "Unknown error")
        raise RuntimeError(error)

    manifest = result.get("manifest", {})
    columns = [col["name"] for col in manifest.get("schema", {}).get("columns", [])]
    data_array = result.get("result", {}).get("data_array", [])
    return [dict(zip(columns, row)) for row in data_array]


if st.button("Run query", disabled=not warehouse_id or not table_name):
    query = f"SELECT * FROM {table_name} LIMIT 3"
    st.code(query, language="sql")
    st.caption(f"Warehouse ID: `{warehouse_id}`")
    try:
        with st.spinner("Running query as current user..."):
            preview = run_sql(query)
        if preview:
            st.dataframe(preview, use_container_width=True)
        else:
            st.info("Table is empty.")
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 403:
            st.error(
                "**403 Forbidden** — the OBO token lacks the `sql` scope. "
                "Go to **Compute > Apps > obo-test-dev > Settings** and add the "
                "`sql` scope under **User Authorization**."
            )
            st.code(e.response.text)
        else:
            st.error(f"Query failed: {e}")
            st.code(e.response.text)
    except Exception as e:
        st.error(f"Query failed: {e}")
