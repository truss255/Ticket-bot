#!/usr/bin/env python3
"""
Script to fix the syntax error in app.py
"""

def fix_app_py():
    """Fix the syntax error in app.py"""
    try:
        # Read the file
        with open('app.py', 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Find the problematic section
        start_line = None
        end_line = None
        
        for i, line in enumerate(lines):
            if '# Use the template to create the ticket submission message blocks' in line:
                start_line = i
            if start_line is not None and ']' in line and 'message_blocks[-1]["elements"]' in lines[i+1]:
                end_line = i + 1
                break
        
        if start_line is not None and end_line is not None:
            # Replace the problematic section with the fixed code
            fixed_lines = lines[:start_line]
            fixed_lines.extend([
                '                    # Use the template to create the ticket submission message blocks\n',
                '                    logger.info(f"Creating ticket submission blocks using template for ticket ID: {ticket_id}")\n',
                '                    message_blocks = get_ticket_submission_blocks(\n',
                '                        ticket_id=ticket_id,\n',
                '                        campaign=campaign,\n',
                '                        issue_type=issue_type,\n',
                '                        priority=priority,\n',
                '                        user_id=user_id,\n',
                '                        details=details,\n',
                '                        salesforce_link=salesforce_link,\n',
                '                        file_url=file_url\n',
                '                    )\n',
            ])
            fixed_lines.extend(lines[end_line+1:])
            
            # Write the fixed content back to the file
            with open('app.py', 'w', encoding='utf-8') as f:
                f.writelines(fixed_lines)
            
            print("Successfully fixed app.py!")
            return True
        else:
            print("Could not find the problematic section in app.py")
            return False
    except Exception as e:
        print(f"Error fixing app.py: {e}")
        return False

if __name__ == "__main__":
    fix_app_py()
