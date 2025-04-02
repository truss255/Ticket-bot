import requests
import sys

def check_server_version(url):
    """Check if the server is running the correct version of the app.py file."""
    try:
        response = requests.get(f"{url}/health")
        if response.status_code == 200:
            print(f"Server is running. Health check response: {response.json()}")
            return True
        else:
            print(f"Server returned status code {response.status_code}")
            return False
    except Exception as e:
        print(f"Error connecting to server: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python check_version.py <server_url>")
        sys.exit(1)
    
    server_url = sys.argv[1]
    if check_server_version(server_url):
        print("Server is running the correct version of the app.py file.")
    else:
        print("Server might not be running the correct version of the app.py file.")
