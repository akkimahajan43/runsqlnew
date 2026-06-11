import os
import json
import time
import sqlite3
from io import BytesIO
from datetime import datetime

import httpx
import plotly.express as px
import pandas as pd
import pyodbc
import sqlalchemy
import sqlparse
import streamlit as st
from dotenv import load_dotenv
from groq import Groq
from st_aggrid import AgGrid, GridOptionsBuilder
from streamlit_ace import st_ace
from streamlit_autorefresh import st_autorefresh

# =========================================================
# LOAD ENV VARIABLES
# =========================================================

load_dotenv()
api_key = os.getenv("GROQ_API_KEY")
http_client = httpx.Client(verify=False)

# =========================================================
# GROQ CONFIG
# =========================================================

client = Groq(
    api_key=api_key,
    http_client=http_client
)

# =========================================================
# PAGE CONFIG
# =========================================================

st.set_page_config(
    page_title="AI SQL Testing Agent",
    layout="wide"
)
st.markdown("""
<style>
pre {
    white-space: pre-wrap !important;
    overflow-x: hidden !important;
    word-break: break-word !important;
}

code {
    white-space: pre-wrap !important;
}
</style>
""", unsafe_allow_html=True)
st.title("AI Powered SQL Testing Agent")
st.markdown("""
<div style="
padding:20px;
border-radius:15px;
background:linear-gradient(90deg,#4F46E5,#06B6D4);
color:white;
margin-bottom:20px;">
<h2>🚀 AI SQL Testing & Reporting Agent</h2>
<p>Generate AI Test Cases, Validate Data Quality, Run Natural Language Reports, and Analyze Results.</p>
</div>
""", unsafe_allow_html=True)

# =========================================================
# FOLDERS
# =========================================================

DB_FOLDER = "databases"
os.makedirs(DB_FOLDER, exist_ok=True)

# =========================================================
# CREATE DEFAULT DATABASE
# =========================================================

default_db = os.path.join(
    DB_FOLDER,
    "names.db"
)

if not os.path.exists(default_db):
    conn = sqlite3.connect(default_db)
    cursor = conn.cursor()

    # CUSTOMERS
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS customers (
        customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_name TEXT,
        email TEXT,
        city TEXT
    )
    """)

    # ORDERS
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        order_id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER,
        order_amount REAL,
        order_date TEXT,
        FOREIGN KEY(customer_id)
            REFERENCES customers(customer_id)
    )
    """)

    # PAYMENTS
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS payments (
        payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER,
        payment_amount REAL,
        payment_status TEXT,
        FOREIGN KEY(order_id)
            REFERENCES orders(order_id)
    )
    """)

    # CUSTOMERS DATA
    customers_data = [
        ("Akshay", "mcleanjason@example.net", "Pune"),
        ("Rahul", "meganburke@example.net", "Mumbai"),
        ("Priya", None, "Nashik"),
        ("Akshay", "mcleanjason@example.net", "Pune")  # Duplicate
    ]

    cursor.executemany("""
    INSERT INTO customers (customer_name, email, city)
    VALUES (?, ?, ?)
    """, customers_data)

    # ORDERS DATA
    orders_data = [
        (1, 1000.00, "2026-01-10"),
        (1, 2000.00, "2026-01-11"),
        (2, 1500.00, "2026-01-12"),
        (99, 500.00, "2026-01-13")  # Invalid customer
    ]

    cursor.executemany("""
    INSERT INTO orders (customer_id, order_amount, order_date)
    VALUES (?, ?, ?)
    """, orders_data)

    # PAYMENTS DATA
    payments_data = [
        (1, 1000.00, "SUCCESS"),
        (2, 2000.00, "SUCCESS"),
        (3, 1200.00, "FAILED"),
        (99, 500.00, "SUCCESS")  # Invalid order
    ]

    cursor.executemany("""
    INSERT INTO payments (order_id, payment_amount, payment_status)
    VALUES (?, ?, ?)
    """, payments_data)

    conn.commit()
    conn.close()


# =========================================================
# HELPER UTILITIES & BACKEND LOGIC
# =========================================================

def get_schema(cursor):
    schema_text = ""
    cursor.execute("""
    SELECT name FROM sqlite_master 
    WHERE type='table' AND name NOT LIKE 'sqlite_%'
    """)
    tables = cursor.fetchall()

    for table in tables:
        table_name = table[0]
        schema_text += "\n" + "=" * 60 + "\n"
        schema_text += f"TABLE: {table_name}\n"
        schema_text += "=" * 60 + "\n"

        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()
        schema_text += "\nColumns:\n"
        for col in columns:
            schema_text += f"- {col[1]} ({col[2]}) {'PRIMARY KEY' if col[5] else ''}\n"

        cursor.execute(f"PRAGMA foreign_key_list({table_name})")
        foreign_keys = cursor.fetchall()
        if foreign_keys:
            schema_text += "\nRelationships:\n"
            for fk in foreign_keys:
                schema_text += f"- {table_name}.{fk[3]} --> {fk[2]}.{fk[4]}\n"

        try:
            cursor.execute(f"SELECT * FROM {table_name} LIMIT 3")
            sample_rows = cursor.fetchall()
            if sample_rows:
                schema_text += "\nSample Rows:\n"
                for row in sample_rows:
                    schema_text += f"{str(row)}\n"
        except Exception:
            pass
        schema_text += "\n"
    return schema_text


def is_safe_query(query):
    dangerous_keywords = ["DROP", "DELETE", "TRUNCATE", "ALTER", "UPDATE"]
    query_upper = query.upper()
    for word in dangerous_keywords:
        if word in query_upper:
            return False
    return True


# =========================================================
# REPORTING ENGINE FUNCTIONS
# =========================================================

def generate_sql(question, schema_text):
    prompt = f"""
    You are an expert SQL Data Analyst specializing in SQLite syntax.
    Given the following database schema structure, construct a clean, optimized SQL query to answer the user's reporting question.

    Database Schema:
    {schema_text}

    User Question:
    "{question}"

    Rules:
    1. Output ONLY the raw executable SQL statement block. No Markdown wrapper text, no explanations, no trailing thoughts.
    2. Use SELECT queries only.
    3. Use aggregations or JOINs appropriately where specified or contextually needed.
    """
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )
    raw_output = response.choices[0].message.content.strip()
    return raw_output.replace("```sql", "").replace("```", "").strip()


# =========================================================
# CREATE REPORTING CHART
# =========================================================

def create_chart(df):
    if df.empty or len(df.columns) < 2:
        return None

    # Force localized reference to prevent openpyxl conflict bugs
    import plotly.express as safe_px

    cols = df.columns.tolist()
    numeric_cols = df.select_dtypes(include=['number']).columns.tolist()

    if not numeric_cols:
        return None

    metric_keywords = ["amount", "total", "sum", "count", "price", "quantity", "received", "revenue"]

    y_axis = None
    for col in numeric_cols:
        if any(kw in col.lower() for kw in metric_keywords):
            y_axis = col
            break

    if not y_axis:
        y_axis = numeric_cols[-1]

    remaining_cols = [c for c in cols if c != y_axis]

    x_axis = remaining_cols[0]
    for col in remaining_cols:
        if any(kw in col.lower() for kw in ["name", "date", "city", "category", "status"]):
            x_axis = col
            break

    if x_axis == y_axis:
        return None

    clean_x = str(x_axis).replace("_", " ").title()
    clean_y = str(y_axis).replace("_", " ").title()

    if "date" in str(x_axis).lower():
        fig = safe_px.line(
            df,
            x=x_axis,
            y=y_axis,
            title=f"{clean_y} Trends over Time by {clean_x}",
            markers=True
        )
    else:
        fig = safe_px.bar(
            df,
            x=x_axis,
            y=y_axis,
            title=f"{clean_y} Breakdown by {clean_x}",
            color=x_axis
        )

    fig.update_layout(
        template="plotly_white",
        xaxis_title=clean_x,
        yaxis_title=clean_y
    )
    return fig


# =========================================================
# SIDEBAR NAVIGATION & CONFIG
# =========================================================

st.sidebar.markdown("## Navigation")

page = st.sidebar.radio(
    "Navigation",
    [
        "🛢️ Table List",
        "🔍 AI Testing",
        "📊 Ask Reporting",
        "📝 SQL Runner"
    ],
    label_visibility="collapsed"
)

# ---------------------------------------------------------
# UNIFIED SMART RESET ACTION ENGINE
# ---------------------------------------------------------
if st.sidebar.button("🔄 Reset Current View", width='stretch'):
    if page == "🛢️ Table List":
        st.session_state.selected_table_tab = "-- Select a Table --"
    elif page == "🔍 AI Testing":
        st.session_state.ai_test_requirement = ""
        st.session_state.ai_test_cases = None
        st.session_state.ai_test_results = None
    elif page == "📊 Ask Reporting":
        st.session_state.reporting_history = []
    elif page == "📝 SQL Runner":
        st.session_state.runner_code_input = "\nSELECT *\nFROM customers;\n"
        st.session_state.runner_execution_cache = None
    st.rerun()

st.sidebar.markdown("---")
db_files = [f for f in os.listdir(DB_FOLDER) if f.endswith(".db")]
selected_db = st.sidebar.selectbox("Select Database", db_files)
db_path = os.path.join(DB_FOLDER, selected_db)

# =========================================================
# DATABASE CONNECTION
# =========================================================

conn = sqlite3.connect(db_path, check_same_thread=False)
cursor = conn.cursor()

# =========================================================
# SIDEBAR DATABASE EXPLORER
# =========================================================

st.sidebar.header("Database Explorer")
cursor.execute("""
SELECT name FROM sqlite_master 
WHERE type='table' AND name NOT LIKE 'sqlite_%'
""")
tables = cursor.fetchall()

for table in tables:
    table_name = table[0]
    with st.sidebar.expander(f"📋 {table_name}"):
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()
        st.write("Columns")
        for col in columns:
            st.write(f"• {col[1]} ({col[2]})")

        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        count = cursor.fetchone()[0]
        st.caption(f"Rows: {count}")

# =========================================================
# PAGE 1: SHOW SAMPLE DATA (PERSISTED - FIXED LAG)
# =========================================================

if page == "🛢️ Table List":
    st.header("🛢️ Table List")

    if "selected_table_tab" not in st.session_state:
        st.session_state.selected_table_tab = "-- Select a Table --"

    cursor.execute("""
    SELECT name FROM sqlite_master 
    WHERE type='table' AND name NOT LIKE 'sqlite_%'
    """)
    all_tables = [table[0] for table in cursor.fetchall()]

    if all_tables:
        options = ["-- Select a Table --"] + all_tables

        # Sync the index position instantly based on current session_state
        default_idx = 0
        if st.session_state.selected_table_tab in options:
            default_idx = options.index(st.session_state.selected_table_tab)

        # Directly mapping the key parameter forces instant single-click rendering
        selected_table = st.selectbox(
            "Choose a Table to View Data",
            options,
            index=default_idx,
            key="selected_table_tab"
        )

        if selected_table != "-- Select a Table --":
            st.subheader(f"📋 Table: {selected_table}")
            try:
                df = pd.read_sql_query(f"SELECT * FROM {selected_table}", conn)
                gb = GridOptionsBuilder.from_dataframe(df)
                gb.configure_default_column(resizable=True, filter=True, sortable=True)
                grid_options = gb.build()

                AgGrid(
                    df,
                    gridOptions=grid_options,
                    height=500,
                    width="100%",
                    columns_auto_size_mode="FIT_CONTENTS"
                )
            except Exception as e:
                st.error(f"Error loading {selected_table}: {e}")
        else:
            st.info("Please select a table from the dropdown above to view its contents.")
    else:
        st.info("No data tables found in the current database.")

# =========================================================
# PAGE 2: AI TEST CASE GENERATOR (PERSISTED)
# =========================================================

if page == "🔍 AI Testing":
    st.markdown("""
        <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 5px;">
            <span style="font-size: 32px;">🎯</span>
            <h1 style="margin: 0; padding: 0; font-size: 30px;">AI Precision Validation</h1>
        </div>
    """, unsafe_allow_html=True)
    st.caption(
        "Auto-generate edge cases, check relational constraints, and verify database schemas using LLM workflows.")

    st.markdown("""
    **💡 Quick-Copy Examples:**
    * `Validate duplicate customers`
    * `Find orders without customers`
    * `Find payments without orders`
    """)

    if "ai_test_requirement" not in st.session_state:
        st.session_state.ai_test_requirement = ""
    if "ai_test_cases" not in st.session_state:
        st.session_state.ai_test_cases = None
    if "ai_test_results" not in st.session_state:
        st.session_state.ai_test_results = None

    requirement = st.text_area(
        "Enter Validation Requirement",
        value=st.session_state.ai_test_requirement,
        placeholder="Type or paste your data quality validation rule here..."
    )
    st.session_state.ai_test_requirement = requirement

    if st.button("Generate AI Test Cases"):
        if requirement.strip() == "":
            st.warning("Please enter requirement.")
        else:
            try:
                schema = get_schema(cursor)
                prompt = f"""
                You are a Senior SQL Testing Expert.
                Database Schema:
                {schema}
                User Requirement:
                {requirement}

                Generate ONLY valid JSON format:
                [
                  {{
                    "test_case":"...",
                    "sql":"..."
                  }}
                ]
                Rules: SQLite syntax, SELECT statements only, return failing validation rows.
                """

                response = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0
                )
                output = response.choices[0].message.content
                output = output.replace("```json", "").replace("```", "").strip()

                try:
                    test_cases = json.loads(output)
                    st.session_state.ai_test_cases = test_cases
                except json.JSONDecodeError:
                    st.error("Invalid JSON returned by AI")
                    st.code(output)
                    st.stop()

                all_results = []
                computed_runs = []

                for index, tc in enumerate(test_cases):
                    sql = tc["sql"]
                    if not is_safe_query(sql):
                        continue

                    try:
                        start_time = time.time()
                        cursor.execute(sql)
                        data = cursor.fetchall()
                        columns = [desc[0] for desc in cursor.description]
                        df_run = pd.DataFrame(data, columns=columns)
                        end_time = time.time()
                        execution_time = round(end_time - start_time, 4)

                        status = "PASS" if len(df_run) == 0 else "FAIL"

                        computed_runs.append({
                            "index": index + 1,
                            "test_case": tc["test_case"],
                            "sql": sql,
                            "df": df_run,
                            "status": status,
                            "execution_time": execution_time
                        })

                        all_results.append({
                            "Test Case": tc["test_case"],
                            "Status": status,
                            "Execution Time": execution_time
                        })
                    except Exception as e:
                        st.error(f"Execution Error: {e}")

                st.session_state.ai_test_results = {
                    "runs": computed_runs,
                    "summary": pd.DataFrame(all_results),
                    "total": len(all_results),
                    "passed": len([x for x in all_results if x["Status"] == "PASS"]),
                    "failed": len([x for x in all_results if x["Status"] == "FAIL"])
                }

            except Exception as e:
                st.error(f"Error: {str(e)}")

    if st.session_state.ai_test_cases and st.session_state.ai_test_results:
        st.success("Test cases loaded successfully!")

        results_data = st.session_state.ai_test_results

        for tc_run in results_data["runs"]:
            st.subheader(f"Test Case {tc_run['index']}")
            st.write(tc_run["test_case"])
            formatted_sql = sqlparse.format(tc_run["sql"], reindent=True, keyword_case="upper")
            st.code(formatted_sql, language="sql")

        st.header("Execution Results")
        for tc_run in results_data["runs"]:
            st.subheader(f"Running: {tc_run['test_case']}")
            formatted_sql = sqlparse.format(tc_run["sql"], reindent=True, keyword_case="upper")

            with st.expander("View SQL Query", expanded=False):
                st.code(formatted_sql, language="sql")

            if tc_run["status"] == "PASS":
                st.markdown(
                    '<div style="padding:15px;border-radius:10px;background:linear-gradient(90deg,#15803D,#4ADE80);border-left:6px solid green;color:white;"><h3>✅ PASS</h3>No violating records found</div>',
                    unsafe_allow_html=True)
            else:
                st.markdown(
                    f'<div style="padding:15px;border-radius:10px;background:linear-gradient(90deg,#991B1B,#F87171);border-left:6px solid red;color:white;"><h3>❌ FAIL</h3>{len(tc_run["df"])} violating record(s) found</div>',
                    unsafe_allow_html=True)
                gb = GridOptionsBuilder.from_dataframe(tc_run["df"])
                gb.configure_default_column(resizable=True, filter=True, sortable=True)
                grid_options = gb.build()
                AgGrid(tc_run["df"], gridOptions=grid_options, height=250, width='100%',
                       columns_auto_size_mode="FIT_CONTENTS")

        st.header("Execution Summary")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Tests", results_data["total"])
        with col2:
            st.metric("Passed", results_data["passed"])
        with col3:
            st.metric("Failed", results_data["failed"])

        st.dataframe(results_data["summary"], width='stretch')

# =========================================================
# PAGE 3: INTERACTIVE REPORTING DASHBOARD (PERSISTED)
# =========================================================

if page == "📊 Ask Reporting":
    st.markdown("""
        <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 5px;">
            <span style="font-size: 32px;">📈</span>
            <h1 style="margin: 0; padding: 0; font-size: 30px;">Conversational Business Reporting</h1>
        </div>
    """, unsafe_allow_html=True)
    st.caption(
        "Ask natural language business questions below to dynamically build visual metrics, summaries, or audit logs.")

    st.markdown("""
    **💡 Quick-Copy Examples:**
    * `show me all customer data`
    * `orders by date`
    * `customer by city`
    """)

    if "reporting_history" not in st.session_state:
        st.session_state.reporting_history = []

    current_schema = get_schema(cursor)

    for interaction in st.session_state.reporting_history:
        with st.chat_message("user"):
            st.write(interaction["question"])
        with st.chat_message("assistant"):
            st.markdown("**Generated SQL Query:**")
            st.code(interaction["sql"], language="sql")
            st.subheader("Data Summary View")
            st.dataframe(interaction["df"], width='stretch')
            if interaction["fig"]:
                st.plotly_chart(interaction["fig"], width='stretch')

    question = st.chat_input("Ask a business question about your dataset here...")

    if question:
        with st.chat_message("user"):
            st.write(question)

        with st.spinner("Generating Report Matrix..."):
            sql_query = generate_sql(question, current_schema)

        with st.chat_message("assistant"):
            st.markdown("**Generated SQL Query:**")
            st.code(sql_query, language="sql")

            if not is_safe_query(sql_query):
                st.error("Dangerous structural alteration query blocked.")
            else:
                try:
                    df = pd.read_sql_query(sql_query, conn)
                    st.subheader("Data Summary View")
                    st.dataframe(df, width='stretch')

                    fig = create_chart(df)
                    if fig:
                        st.plotly_chart(fig, width='stretch')

                    st.session_state.reporting_history.append({
                        "question": question,
                        "sql": sql_query,
                        "df": df,
                        "fig": fig
                    })

                except Exception as e:
                    st.error(f"Execution Engine Error: {str(e)}")

# =========================================================
# PAGE 4: MANUAL SQL QUERY RUNNER (PERSISTED)
# =========================================================

if page == "📝 SQL Runner":
    st.header("📝 Manual SQL Query Runner")

    if "runner_code_input" not in st.session_state:
        st.session_state.runner_code_input = "\nSELECT *\nFROM customers;\n"
    if "runner_execution_cache" not in st.session_state:
        st.session_state.runner_execution_cache = None

    uploaded_file = st.file_uploader("Upload SQL File", type=["sql"])

    if uploaded_file is not None:
        query_text = uploaded_file.read().decode("utf-8")
        st.session_state.runner_code_input = query_text
    else:
        query_text = st.session_state.runner_code_input

    query = st_ace(value=query_text, language="sql", theme="xcode", height=300, auto_update=True)
    st.session_state.runner_code_input = query

    col1, col2 = st.columns([1, 1])
    with col1:
        run_query = st.button("Run Manual Query", width='stretch')
    with col2:
        clear_query = st.button("Clear Query", width='stretch')

    if clear_query:
        st.session_state.runner_code_input = ""
        st.session_state.runner_execution_cache = None
        st.rerun()

    if run_query:
        try:
            start_time = time.time()
            queries = [q.strip() for q in query.split(";") if q.strip()]

            if len(queries) == 0:
                st.warning("Please enter a query.")
            else:
                computed_tabs = []
                for i, sql in enumerate(queries):
                    if not is_safe_query(sql):
                        continue

                    cursor.execute(sql)
                    if cursor.description:
                        data = cursor.fetchall()
                        columns = [desc[0] for desc in cursor.description]
                        df_res = pd.DataFrame(data, columns=columns)
                        computed_tabs.append({"type": "select", "sql": sql, "data": df_res})
                    else:
                        conn.commit()
                        computed_tabs.append({"type": "commit", "sql": sql, "data": "Query executed successfully!"})

                end_time = time.time()
                execution_time = round(end_time - start_time, 4)

                st.session_state.runner_execution_cache = {
                    "tabs": computed_tabs,
                    "time": execution_time
                }

        except Exception as e:
            st.error(f"Error: {str(e)}")

    if st.session_state.runner_execution_cache:
        cached = st.session_state.runner_execution_cache
        tabs_elements = st.tabs([f"📄 Query-{i + 1}" for i in range(len(cached["tabs"]))])

        for i, tab_data in enumerate(cached["tabs"]):
            with tabs_elements[i]:
                formatted_sql = sqlparse.format(tab_data["sql"], reindent=True, keyword_case="upper")
                st.code(formatted_sql, language="sql")

                if tab_data["type"] == "select":
                    gb = GridOptionsBuilder.from_dataframe(tab_data["data"])
                    gb.configure_default_column(resizable=True, filter=True, sortable=True)
                    grid_options = gb.build()
                    AgGrid(tab_data["data"], gridOptions=grid_options, height=300, width="100%",
                           columns_auto_size_mode="FIT_CONTENTS")
                else:
                    st.success(tab_data["data"])

        st.success(f"Execution Time:\n{cached['time']} sec")

# =========================================================
# CLOSE CONNECTION
# =========================================================
conn.close()