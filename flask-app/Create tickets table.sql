-- Create the tickets table
CREATE TABLE tickets (
    ticket_id SERIAL PRIMARY KEY,
    created_by VARCHAR(255) NOT NULL,
    campaign VARCHAR(255) NOT NULL,
    issue_type VARCHAR(255) NOT NULL,
    priority VARCHAR(50) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'Open',
    assigned_to VARCHAR(255) DEFAULT 'Unassigned',
    details TEXT NOT NULL,
    salesforce_link TEXT DEFAULT NULL,
    file_url TEXT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create comments table for ticket comments
CREATE TABLE comments (
    comment_id SERIAL PRIMARY KEY,
    ticket_id INTEGER REFERENCES tickets(ticket_id),
    user_id VARCHAR(255) NOT NULL,
    comment_text TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create the updated_at trigger function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create the trigger
CREATE TRIGGER set_updated_at
    BEFORE UPDATE ON tickets
    FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();
