import os
import json
import time
import httpx
import sqlite3
import sqlparse
import pandas as pd
from groq import Groq
from io import BytesIO
import streamlit as st
from datetime import datetime
from dotenv import load_dotenv
from streamlit_ace import st_ace
from st_aggrid import AgGrid, GridOptionsBuilder
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
<h2>🚀 AI SQL Testing Agent</h2>
<p>Generate AI Test Cases, Validate Data Quality, Execute SQL and Analyze Results.</p>
</div>
""", unsafe_allow_html=True)

# =========================================================
# AUTO REFRESH
# =========================================================

# st_autorefresh(
#    interval=10000,
#    key="refresh"
# )

# =========================================================
# FOLDERS
# =========================================================

DB_FOLDER = "databases"
HISTORY_FOLDER = "sql_history"

os.makedirs(DB_FOLDER, exist_ok=True)
os.makedirs(HISTORY_FOLDER, exist_ok=True)

HISTORY_FILE = os.path.join(
    HISTORY_FOLDER,
    "history.json"
)

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

    # =====================================================
    # CUSTOMERS
    # =====================================================
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS customers (
        customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_name TEXT,
        email TEXT,
        city TEXT
    )
    """)

    # =====================================================
    # ORDERS
    # =====================================================
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

    # =====================================================
    # PAYMENTS
    # =====================================================
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

    # =====================================================
    # CUSTOMERS DATA
    # =====================================================
    customers_data = [
        ("Akshay", "akshay@test.com", "Pune"),
        ("Rahul", "rahul@test.com", "Mumbai"),
        ("Priya", None, "Nashik"),
        ("Akshay", "akshay@test.com", "Pune")  # Duplicate
    ]

    cursor.executemany("""
    INSERT INTO customers (
        customer_name,
        email,
        city
    )
    VALUES (?, ?, ?)
    """, customers_data)

    # =====================================================
    # ORDERS DATA
    # =====================================================
    orders_data = [
        (1, 1000.00, "2026-01-10"),
        (1, 2000.00, "2026-01-11"),
        (2, 1500.00, "2026-01-12"),
        (99, 500.00, "2026-01-13")  # Invalid customer
    ]

    cursor.executemany("""
    INSERT INTO orders (
        customer_id,
        order_amount,
        order_date
    )
    VALUES (?, ?, ?)
    """, orders_data)

    # =====================================================
    # PAYMENTS DATA
    # =====================================================
    payments_data = [
        (1, 1000.00, "SUCCESS"),
        (2, 2000.00, "SUCCESS"),
        (3, 1200.00, "FAILED"),
        (99, 500.00, "SUCCESS")  # Invalid order
    ]

    cursor.executemany("""
    INSERT INTO payments (
        order_id,
        payment_amount,
        payment_status
    )
    VALUES (?, ?, ?)
    """, payments_data)

    conn.commit()
    conn.close()


# =========================================================
# LOAD HISTORY
# =========================================================

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    return []


# =========================================================
# SAVE HISTORY
# =========================================================

def save_history(query):
    history = load_history()
    history.insert(0, {
        "query": query,
        "time": datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    })
    history = history[:20]
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=4)


# =========================================================
# GET DATABASE SCHEMA (MULTI-TABLE SUPPORT)
# =========================================================

def get_schema(cursor):
    schema_text = ""
    cursor.execute("""
    SELECT name
    FROM sqlite_master
    WHERE type='table'
    AND name NOT LIKE 'sqlite_%'
    """)
    tables = cursor.fetchall()

    for table in tables:
        table_name = table[0]
        schema_text += "\n" + "=" * 60 + "\n"
        schema_text += f"TABLE: {table_name}\n"
        schema_text += "=" * 60 + "\n"

        # -----------------------------------------
        # Columns
        # -----------------------------------------
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()
        schema_text += "\nColumns:\n"
        for col in columns:
            schema_text += (
                f"- {col[1]} "
                f"({col[2]}) "
                f"{'PRIMARY KEY' if col[5] else ''}\n"
            )

        # -----------------------------------------
        # Foreign Keys
        # -----------------------------------------
        cursor.execute(f"PRAGMA foreign_key_list({table_name})")
        foreign_keys = cursor.fetchall()
        if foreign_keys:
            schema_text += "\nRelationships:\n"
            for fk in foreign_keys:
                schema_text += (
                    f"- {table_name}.{fk[3]} "
                    f"--> "
                    f"{fk[2]}.{fk[4]}\n"
                )

        # -----------------------------------------
        # Sample Data
        # -----------------------------------------
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


# =========================================================
# BLOCK DANGEROUS QUERIES
# =========================================================

def is_safe_query(query):
    dangerous_keywords = ["DROP", "DELETE", "TRUNCATE", "ALTER", "UPDATE"]
    query_upper = query.upper()
    for word in dangerous_keywords:
        if word in query_upper:
            return False
    return True


# =========================================================
# SIDEBAR DATABASE
# =========================================================
st.sidebar.header("Database")
st.sidebar.markdown("## Navigation")

page = st.sidebar.radio(
    "Navigation",
    [
        "📊 Sample Data",
        "🤖 AI Testing",
        "📝 SQL Runner"
    ],
    label_visibility="collapsed"
)
db_files = [f for f in os.listdir(DB_FOLDER) if f.endswith(".db")]

selected_db = st.sidebar.selectbox(
    "Select Database",
    db_files
)

db_path = os.path.join(
    DB_FOLDER,
    selected_db
)

# =========================================================
# DATABASE CONNECTION
# =========================================================

conn = sqlite3.connect(
    db_path,
    check_same_thread=False
)
cursor = conn.cursor()

# =========================================================
# SIDEBAR DATABASE EXPLORER
# =========================================================

st.sidebar.header("Database Explorer")

cursor.execute("""
SELECT name
FROM sqlite_master
WHERE type='table'
AND name NOT LIKE 'sqlite_%'
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
# QUERY HISTORY
# =========================================================

st.sidebar.header("Query History")
history = load_history()

for item in history:
    with st.sidebar.expander(item["time"]):
        st.code(item["query"], language="sql")

# =========================================================
# SHOW SAMPLE DATA (MODIFIED FOR MANUAL TABLE SELECTION)
# =========================================================

if page == "📊 Sample Data":
    st.header("📊 Sample Data")

    # Fetch all available tables
    cursor.execute("""
    SELECT name
    FROM sqlite_master
    WHERE type='table'
    AND name NOT LIKE 'sqlite_%'
    """)
    all_tables = [table[0] for table in cursor.fetchall()]

    if all_tables:
        # Insert a blank placeholder at index 0 so no table loads automatically
        options = ["-- Select a Table --"] + all_tables
        selected_table = st.selectbox("Choose a Table to View Data", options, index=0)

        # Only query and display data if the user has chosen a real table
        if selected_table != "-- Select a Table --":
            st.subheader(f"📋 Table: {selected_table}")
            try:
                df = pd.read_sql_query(f"SELECT * FROM {selected_table}", conn)
                gb = GridOptionsBuilder.from_dataframe(df)
                gb.configure_default_column(
                    resizable=True,
                    filter=True,
                    sortable=True
                )
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
# AI TEST CASE GENERATOR
# =========================================================

if page == "🤖 AI Testing":
    st.header("🤖 AI Test Case Generator")

    requirement = st.text_area(
        "Enter Validation Requirement",
        placeholder="""
Examples:
- Validate duplicate customers
- Find orders without customers
- Find payments without orders
- Validate null emails
- Check failed payments
"""
    )

    # =========================================================
    # GENERATE AI TEST CASES
    # =========================================================
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

                Generate ONLY valid JSON.

                Format:

                [
                  {{
                    "test_case":"...",
                    "sql":"..."
                  }}
                ]

                Rules:

                1. Use SQLite syntax.
                2. Use only SELECT statements.
                3. Never generate:
                   - DELETE
                   - DROP
                   - UPDATE
                   - ALTER
                   - TRUNCATE
                4. Use JOINs whenever tables are related.
                5. Consider foreign-key relationships.
                6. Generate data-quality test cases.
                7. Generate validation queries that return failing records.
                8. Empty result = PASS.
                9. Return valid JSON only.
                """

                response = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0
                )

                output = response.choices[0].message.content

                # =================================================
                # CLEAN MARKDOWN
                # =================================================
                output = output.replace("```json", "").replace("```", "").strip()

                # =================================================
                # SAFE JSON PARSE
                # =================================================
                try:
                    test_cases = json.loads(output)
                except json.JSONDecodeError:
                    st.error("Invalid JSON returned by AI")
                    st.code(output)
                    st.stop()

                st.success("Test cases generated successfully!")

                # =================================================
                # DISPLAY TEST CASES
                # =================================================
                for index, tc in enumerate(test_cases):
                    st.subheader(f"Test Case {index + 1}")
                    st.write(tc["test_case"])
                    formatted_sql = sqlparse.format(
                        tc["sql"],
                        reindent=True,
                        keyword_case="upper"
                    )
                    st.code(formatted_sql, language="sql")

                # =================================================
                # EXECUTE TEST CASES
                # =================================================
                st.header("Execution Results")
                all_results = []

                for index, tc in enumerate(test_cases):
                    sql = tc["sql"]
                    st.subheader(f"Running: {tc['test_case']}")
                    formatted_sql = sqlparse.format(
                        sql,
                        reindent=True,
                        keyword_case="upper"
                    )

                    with st.expander("View SQL Query", expanded=True):
                        st.code(formatted_sql, language="sql")

                    # =============================================
                    # SAFETY CHECK
                    # =============================================
                    if not is_safe_query(sql):
                        st.error("Dangerous query blocked!")
                        continue

                    try:
                        start_time = time.time()
                        cursor.execute(sql)
                        data = cursor.fetchall()
                        columns = [desc[0] for desc in cursor.description]
                        df = pd.DataFrame(data, columns=columns)
                        end_time = time.time()
                        execution_time = round(end_time - start_time, 4)

                        clean_sql = sql.replace("\r", "").strip()
                        save_history(clean_sql)

                        # =========================================
                        # PASS / FAIL LOGIC
                        # =========================================
                        if len(df) == 0:
                            status = "PASS"
                            st.markdown("""
                            <div style="
                            padding:15px;
                            border-radius:10px;
                            background:#DCFCE7;
                            border-left:6px solid green;">
                            <h3>✅ PASS</h3>
                            No violating records found
                            </div>
                            """, unsafe_allow_html=True)
                        else:
                            status = "FAIL"
                            st.markdown(f"""
                            <div style="
                            padding:15px;
                            border-radius:10px;
                            background:#FEE2E2;
                            border-left:6px solid red;">
                            <h3>❌ FAIL</h3>
                            {len(df)} violating record(s) found
                            </div>
                            """, unsafe_allow_html=True)

                            gb = GridOptionsBuilder.from_dataframe(df)
                            gb.configure_default_column(
                                resizable=True,
                                filter=True,
                                sortable=True
                            )
                            grid_options = gb.build()

                            AgGrid(
                                df,
                                gridOptions=grid_options,
                                height=500,
                                width='100%',
                                columns_auto_size_mode="FIT_CONTENTS"
                            )

                        all_results.append({
                            "Test Case": tc["test_case"],
                            "Status": status,
                            "Execution Time": execution_time
                        })

                    except Exception as e:
                        st.error(f"Execution Error: {e}")

                # =================================================
                # EXECUTION SUMMARY
                # =================================================
                st.header("Execution Summary")
                col1, col2, col3 = st.columns(3)

                with col1:
                    st.metric("Total Tests", len(all_results))
                with col2:
                    st.metric("Passed", len([x for x in all_results if x["Status"] == "PASS"]))
                with col3:
                    st.metric("Failed", len([x for x in all_results if x["Status"] == "FAIL"]))

                summary_df = pd.DataFrame(all_results)
                st.dataframe(summary_df)

                # =================================================
                # CSV DOWNLOAD
                # =================================================
                csv = summary_df.to_csv(index=False)
                st.download_button(
                    label="Download Summary CSV",
                    data=csv,
                    file_name="test_summary.csv",
                    mime="text/csv"
                )

                # =================================================
                # EXCEL DOWNLOAD
                # =================================================
                output_excel = BytesIO()
                with pd.ExcelWriter(output_excel, engine="openpyxl") as writer:
                    summary_df.to_excel(writer, index=False, sheet_name="Summary")

                excel_data = output_excel.getvalue()
                st.download_button(
                    label="Download Summary Excel",
                    data=excel_data,
                    file_name="test_summary.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

            except Exception as e:
                st.error(f"Error: {str(e)}")

# =========================================================
# MANUAL SQL QUERY RUNNER
# =========================================================

if page == "📝 SQL Runner":
    st.header("📝 Manual SQL Query Runner")

    uploaded_file = st.file_uploader("Upload SQL File", type=["sql"])
    default_query = "\nSELECT *\nFROM customers;\n"

    if uploaded_file is not None:
        query_text = uploaded_file.read().decode("utf-8")
    else:
        query_text = default_query

    query = st_ace(
        value=query_text,
        language="sql",
        theme="xcode",
        height=500,
        auto_update=True
    )

    col1, col2 = st.columns([1, 1])
    with col1:
        run_query = st.button("Run Manual Query", use_container_width=True)
    with col2:
        clear_query = st.button("Clear Query", use_container_width=True)

    if clear_query:
        query = ""

    # =========================================================
    # EXECUTE MANUAL QUERY
    # =========================================================
    if run_query:
        try:
            start_time = time.time()
            queries = [q.strip() for q in query.split(";") if q.strip()]

            if len(queries) == 0:
                st.warning("Please enter a query.")
            else:
                tabs = st.tabs([f"📄 Query-{i + 1}" for i in range(len(queries))])

                for i, sql in enumerate(queries):
                    with tabs[i]:
                        # =====================================
                        # SAFETY CHECK
                        # =====================================
                        if not is_safe_query(sql):
                            st.error(f"Dangerous query blocked:\n{sql}")
                            continue

                        # =====================================
                        # FORMATTED SQL
                        # =====================================
                        formatted_sql = sqlparse.format(
                            sql,
                            reindent=True,
                            keyword_case="upper"
                        )
                        st.code(formatted_sql, language="sql")

                        # =====================================
                        # EXECUTE QUERY
                        # =====================================
                        cursor.execute(sql)

                        if cursor.description:
                            data = cursor.fetchall()
                            columns = [desc[0] for desc in cursor.description]
                            df = pd.DataFrame(data, columns=columns)

                            gb = GridOptionsBuilder.from_dataframe(df)
                            gb.configure_default_column(
                                resizable=True,
                                filter=True,
                                sortable=True
                            )
                            grid_options = gb.build()

                            AgGrid(
                                df,
                                gridOptions=grid_options,
                                height=500,
                                width="100%",
                                columns_auto_size_mode="FIT_CONTENTS"
                            )
                        else:
                            conn.commit()
                            st.success("Query executed successfully!")

            end_time = time.time()
            execution_time = round(end_time - start_time, 4)
            clean_query = query.replace("\r", "").strip()
            save_history(clean_query)

            st.success(f"Execution Time:\n{execution_time} sec")

        except Exception as e:
            st.error(f"Error: {str(e)}")

# =========================================================
# CLOSE CONNECTION
# =========================================================
conn.close()