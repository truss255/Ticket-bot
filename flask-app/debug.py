#!/usr/bin/env python3
"""
Debug script to check for syntax errors in app.py
"""

import sys
import py_compile
import ast

def check_syntax(filename):
    """Check for syntax errors in a Python file"""
    print(f"Checking syntax of {filename}...")
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            source = f.read()
        
        # Try to parse the file
        ast.parse(source)
        print(f"✅ No syntax errors found in {filename}")
        return True
    except SyntaxError as e:
        print(f"❌ Syntax error in {filename} at line {e.lineno}, column {e.offset}")
        print(f"   {e.text.strip()}")
        print(f"   {' ' * (e.offset - 1)}^")
        print(f"   {e}")
        return False
    except Exception as e:
        print(f"❌ Error checking {filename}: {e}")
        return False

def main():
    """Main function"""
    filename = 'app.py'
    if len(sys.argv) > 1:
        filename = sys.argv[1]
    
    if check_syntax(filename):
        print("Syntax check passed!")
        sys.exit(0)
    else:
        print("Syntax check failed!")
        sys.exit(1)

if __name__ == "__main__":
    main()
