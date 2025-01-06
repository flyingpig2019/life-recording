import sqlite3
import pandas as pd

# Define the database file path and the table name
db_path = r"D:\PythonSpace\project1\meter.db"
table_name = "meter_records"
output_csv = "meter_records.csv"

try:
    # Connect to the SQLite3 database
    conn = sqlite3.connect(db_path)
    print("Database connection successful.")
    
    # Query the table and load it into a DataFrame
    query = f"SELECT * FROM {table_name}"
    df = pd.read_sql_query(query, conn)
    print(f"Table '{table_name}' fetched successfully.")
    
    # Save the DataFrame as a CSV file
    df.to_csv(output_csv, index=False)
    print(f"Table '{table_name}' has been saved as '{output_csv}'.")
    
except sqlite3.Error as e:
    print(f"An error occurred: {e}")
finally:
    # Ensure the connection is closed
    if 'conn' in locals():
        conn.close()
        print("Database connection closed.")
