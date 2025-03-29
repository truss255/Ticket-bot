# ...existing code...

def all_tickets_modal():
    return {
        "type": "modal",
        "title": {"type": "plain_text", "text": "All Tickets"},
        "blocks": [
            # ...existing code...
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Export as CSV"},
                        "action_id": "export_csv"
                    },
                    {
                        "type": "static_select",
                        "placeholder": {"type": "plain_text", "text": "Filter by Status"},
                        "action_id": "filter_status",
                        "options": [
                            {"text": {"type": "plain_text", "text": "All"}, "value": "all"},
                            {"text": {"type": "plain_text", "text": "Open"}, "value": "open"},
                            {"text": {"type": "plain_text", "text": "Closed"}, "value": "closed"}
                        ]
                    }
                ]
            }
        ]
    }
