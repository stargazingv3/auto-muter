
import sqlite3
import os

# Define the path for the database.
# It's placed in the backend directory, where it will be used by the FastAPI app.
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'browser-extension', 'backend', 'speakers.db')
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

print(f"Database will be created at: {DB_PATH}")

# Connect to the SQLite database (it will be created if it doesn't exist)
try:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # --- Create the 'speakers' table ---
    # This table stores the unique names of the speakers.
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS speakers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE
    );
    """)
    print("Table 'speakers' created or already exists.")

    # --- Create the 'sources' table ---
    # This table stores the details of each enrollment, linking back to a speaker.
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        speaker_id INTEGER NOT NULL,
        source_url TEXT,
        timestamp TEXT,
        embedding_path TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (speaker_id) REFERENCES speakers (id)
    );
    """)
    print("Table 'sources' created or already exists.")

    # --- Create indexes for faster lookups ---
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_speaker_name ON speakers (name);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_source_speaker_id ON sources (speaker_id);")
    print("Indexes created or already exist.")

    conn.commit()
    print("Database schema initialized successfully.")

except sqlite3.Error as e:
    print(f"Database error: {e}")

finally:
    if conn:
        conn.close()
        print("Connection closed.")

if __name__ == "__main__":
    print("This script should be run from the root of the project.")
    # Example of how to run it: python3 scripts/initialize_database.py
