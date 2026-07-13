"""
GraphQL Client Module.

This module provides functions to interact with the CollectiveAccess GraphQL API,
including logging in and sending queries.
"""

import json
import urllib.request
import urllib.error
import sys
import os
import tomllib

def send_graphql_query(api_server, endpoint, query, jwt_token=None):
    """
    Sends a GraphQL query to the specified endpoint on the API server.

    Variables:
        api_server (str): The base URL of the GraphQL service API.
        endpoint (str): The specific endpoint to query (e.g., 'Search', 'Schema', 'Auth').
        query (str): The GraphQL query string.
        jwt_token (str, optional): The JWT token for authorization. If not provided
            and the endpoint is not 'Auth', the function will attempt to login
            automatically to retrieve a token.

    Expected Outputs:
        dict: The parsed JSON response dictionary from the server.
    """
    url = f"{api_server}/{endpoint}"
    data = json.dumps({"query": query}).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if not jwt_token and endpoint != "Auth":
        jwt_token = login_graphql_api(api_server)
    if jwt_token:
        req.add_header("Authorization", f"Bearer {jwt_token}")
    try:
        with urllib.request.urlopen(req) as response:
            res_body = response.read().decode("utf-8")
            return json.loads(res_body)
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code} for endpoint {endpoint}: {e.reason}", file=sys.stderr)
        try:
            print(e.read().decode("utf-8"), file=sys.stderr)
        except Exception:
            pass
        sys.exit(1)
    except Exception as e:
        print(f"Request failed for endpoint {endpoint}: {e}", file=sys.stderr)
        sys.exit(1)

def login_graphql_api(api_server):
    """
    Authenticates with the CollectiveAccess GraphQL API using credentials loaded from config.toml.

    Variables:
        api_server (str): The base URL of the GraphQL service API.

    Expected Outputs:
        str: The retrieved JWT authentication token string.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_file = os.path.join(script_dir, "config", "config.toml")
    
    # Check/Create config file
    if not os.path.exists(config_file):
        print(f"Error: Configuration file not found at: {config_file}")
        sys.exit(0)
        
    # Load credentials
    with open(config_file, 'rb') as f:
        config = tomllib.load(f)
    username = config.get("username", "")
    password = config.get("password", "")
    
    if not username or username == "username_goes_here" or not password or password == "password_goes_here":
        print("Error: Please provide valid credentials in config.toml.", file=sys.stderr)
        sys.exit(1)
        
    # Login and get token
    print("Authenticating...")
    login_payload = f"""query {{
        login(username:"{username}", password: "{password}")
        {{
                jwt,
                refresh,
                user {{
                        id,
                        email
                }}
        }}
}}"""
    login_response = send_graphql_query(api_server, "Auth", login_payload)
    
    try:
        jwt_token = login_response["data"]["login"]["jwt"]
    except (KeyError, TypeError):
        print(f"Failed to extract JWT token from response: {login_response}", file=sys.stderr)
        sys.exit(1)
    return jwt_token