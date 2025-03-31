CREATE TABLE tickets (
    ticket_id SERIAL PRIMARY KEY,
    created_by VARCHAR(255) NOT NULL,
    campaign VARCHAR(255),
    issue_type VARCHAR(50),
    priority VARCHAR(50),
    status VARCHAR(50),
    assigned_to VARCHAR(255),
    details TEXT,
    salesforce_link TEXT,
    file_url TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE comments (
    comment_id SERIAL PRIMARY KEY,
    ticket_id INT NOT NULL REFERENCES tickets(ticket_id) ON DELETE CASCADE,
    created_by VARCHAR(255) NOT NULL,
    comment_text TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
