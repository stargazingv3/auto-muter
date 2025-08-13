-- Schema for the Auto Muter extension database

CREATE TABLE speakers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    speaker_id INTEGER NOT NULL,
    source_url TEXT,
    timestamp TEXT,
    embedding BLOB NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (speaker_id) REFERENCES speakers (id)
);

CREATE INDEX idx_speaker_name ON speakers (name);
CREATE INDEX idx_source_speaker_id ON sources (speaker_id);

-- Store simple key/value settings (e.g., threshold)
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
