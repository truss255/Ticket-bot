#!/usr/bin/env python3
"""
Script to fix the syntax error in app.py
"""

def fix_app_py():
    """Fix the syntax error in app.py"""
    try:
        # Read the file
        with open('app.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Find the start of the template code
        template_start = content.find('# Use the template to create the ticket submission message blocks')
        
        if template_start == -1:
            print("Could not find template code section")
            return False
        
        # Find the end of the template code (the closing parenthesis)
        template_end = content.find(')', template_start)
        template_end = content.find('\n', template_end) + 1  # Include the newline after the closing parenthesis
        
        if template_end == -1:
            print("Could not find end of template code section")
            return False
        
        # Find the start of the old message blocks code
        old_code_start = content.find('# For backward compatibility', template_end)
        
        if old_code_start == -1:
            print("Could not find old message blocks code")
            return False
        
        # Find the end of the old message blocks code (the closing bracket and the commented out elements line)
        old_code_end = content.find(']', old_code_start)
        old_code_end = content.find('message_blocks[-1]["elements"]', old_code_end)
        old_code_end = content.find('\n', old_code_end) + 1  # Include the newline after the commented out line
        
        if old_code_end == -1:
            print("Could not find end of old message blocks code")
            return False
        
        # Replace the old message blocks code with a comment
        fixed_content = content[:old_code_start] + '                    # Old message blocks code has been removed and replaced with the template\n' + content[old_code_end:]
        
        # Write the fixed content back to the file
        with open('app.py', 'w', encoding='utf-8') as f:
            f.write(fixed_content)
            
        print("Successfully fixed app.py!")
        return True
    except Exception as e:
        print(f"Error fixing app.py: {e}")
        return False

if __name__ == "__main__":
    fix_app_py()
