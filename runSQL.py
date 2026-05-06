from st_aggrid import AgGrid, GridOptionsBuilder
from streamlit_autorefresh import st_autorefresh
from streamlit_ace import st_ace
from datetime import datetime
import streamlit as st
from io import BytesIO
import pandas as pd
import sqlite3
import json
import time
import os

# =========================================================
# PAGE CONFIG
# =========================================================
st.set_page_config(
    page_title="Advanced SQLite Manager",
    layout="wide"
)

st.title("Advanced SQLite Manager")

# =========================================================
# AUTO REFRESH
# =========================================================
st_autorefresh(
    interval=10000,
    key="refresh"
)

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
default_db = os.path.join(DB_FOLDER, "names.db")

if not os.path.exists(default_db):

    conn = sqlite3.connect(default_db)

    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        email TEXT,
        age INTEGER
    )
    """)

    conn.commit()
    conn.close()

# =========================================================
# LOAD QUERY HISTORY
# =========================================================
def load_history():

    if os.path.exists(HISTORY_FILE):

        with open(HISTORY_FILE, "r") as f:
            return json.load(f)

    return []

# =========================================================
# SAVE QUERY HISTORY
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
# SIDEBAR - DATABASE SELECTOR
# =========================================================
st.sidebar.header("Database")

db_files = [
    f for f in os.listdir(DB_FOLDER)
    if f.endswith(".db")
]

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
# SIDEBAR - DATABASE EXPLORER
# =========================================================
st.sidebar.header("Database Explorer")

cursor.execute("""
SELECT name
FROM sqlite_master
WHERE type='table'
""")

tables = cursor.fetchall()

for table in tables:

    table_name = table[0]

    with st.sidebar.expander(table_name):

        cursor.execute(
            f"PRAGMA table_info({table_name})"
        )

        columns = cursor.fetchall()

        for col in columns:

            st.write(
                f"{col[1]} ({col[2]})"
            )

# =========================================================
# SIDEBAR - QUERY HISTORY
# =========================================================
st.sidebar.header("Query History")

history = load_history()

for item in history:

    with st.sidebar.expander(item["time"]):

        st.code(
            item["query"],
            language="sql"
        )

# =========================================================
# USER FORM
# =========================================================
st.header("Add User")

with st.form(
    "user_form",
    clear_on_submit=True
):

    name = st.text_input("Enter Name")

    email = st.text_input("Enter Email")

    age = st.number_input(
        "Enter Age",
        min_value=0,
        step=1
    )

    submitted = st.form_submit_button(
        "Save User"
    )

    if submitted:

        if name.strip() == "":

            st.warning(
                "Please enter a name."
            )

        else:

            try:

                cursor.execute("""
                INSERT INTO users (
                    name,
                    email,
                    age
                )
                VALUES (?, ?, ?)
                """, (
                    name.strip(),
                    email.strip(),
                    int(age)
                ))

                conn.commit()

                st.success(
                    "User saved successfully!"
                )

            except Exception as e:

                st.error(f"Error: {e}")

# =========================================================
# SHOW DATA
# =========================================================
st.header("User Data")

if st.button("Show Users"):

    try:

        df = pd.read_sql_query(
            "SELECT * FROM users",
            conn
        )

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
            height=400,
            width='100%',
            columns_auto_size_mode="FIT_CONTENTS"
        )
    except Exception as e:

        st.error(f"Error: {e}")

# =========================================================
# SQL QUERY RUNNER
# =========================================================
st.header("SQL Query Runner")

# =========================================================
# SQL FILE UPLOAD
# =========================================================
uploaded_file = st.file_uploader(
    "Upload SQL File",
    type=["sql"]
)

default_query = "SELECT * FROM users;"

if uploaded_file is not None:

    query_text = uploaded_file.read().decode(
        "utf-8"
    )

else:

    query_text = default_query

# =========================================================
# SQL EDITOR
# =========================================================
query = st_ace(
    value=query_text,
    language="sql",
    theme="monokai",
    height=300,
    auto_update=True
)

# =========================================================
# BUTTONS
# =========================================================
col1, col2 = st.columns([1, 1])

with col1:

    run_query = st.button(
        "Run Query",
        width="stretch"
    )

with col2:

    clear_query = st.button(
        "Clear Query",
        width="stretch"
    )

if clear_query:

    query = ""

# =========================================================
# RESULT CONTAINER
# =========================================================
result_container = st.empty()

# =========================================================
# EXECUTE QUERY
# =========================================================
if run_query:

    result_container.empty()

    try:

        start_time = time.time()

        query_clean = query.strip().upper()

        # =================================================
        # MULTIPLE SQL STATEMENTS
        # =================================================
        if ";" in query.strip()[:-1]:

            cursor.executescript(query)

            conn.commit()

            end_time = time.time()

            execution_time = round(
                end_time - start_time,
                4
            )

            save_history(query)

            result_container.success(
                f"""
                SQL script executed successfully.
                Execution Time:
                {execution_time} sec
                """
            )

        else:

            cursor.execute(query)

            # =============================================
            # SELECT QUERY
            # =============================================
            if query_clean.startswith("SELECT"):

                data = cursor.fetchall()

                columns = [
                    desc[0]
                    for desc in cursor.description
                ]

                df = pd.DataFrame(
                    data,
                    columns=columns
                )

                end_time = time.time()

                execution_time = round(
                    end_time - start_time,
                    4
                )

                save_history(query)

                st.success(
                    f"""
                    Query executed successfully.
                    Execution Time:
                    {execution_time} sec
                    """
                )

                # =========================================
                # INTERACTIVE GRID
                # =========================================
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
                    height=400,
                    width='100%',
                    columns_auto_size_mode="FIT_CONTENTS"
                )

                # =========================================
                # CSV DOWNLOAD
                # =========================================
                csv = df.to_csv(
                    index=False
                )

                st.download_button(
                    label="Download CSV",
                    data=csv,
                    file_name="query_result.csv",
                    mime="text/csv"
                )

                # =========================================
                # EXCEL DOWNLOAD
                # =========================================
                output = BytesIO()

                with pd.ExcelWriter(
                    output,
                    engine="openpyxl"
                ) as writer:

                    df.to_excel(
                        writer,
                        index=False,
                        sheet_name="Results"
                    )

                excel_data = output.getvalue()

                st.download_button(
                    label="Download Excel",
                    data=excel_data,
                    file_name="query_result.xlsx",
                    mime="""
                    application/vnd.openxmlformats-
                    officedocument.spreadsheetml.sheet
                    """
                )

            # =============================================
            # INSERT / UPDATE / DELETE
            # =============================================
            else:

                conn.commit()

                end_time = time.time()

                execution_time = round(
                    end_time - start_time,
                    4
                )

                save_history(query)

                result_container.success(
                    f"""
                    Query executed successfully.
                    Execution Time:
                    {execution_time} sec
                    """
                )

    except Exception as e:

        result_container.error(
            f"Error: {e}"
        )

# =========================================================
# CLOSE CONNECTION
# =========================================================
conn.close()