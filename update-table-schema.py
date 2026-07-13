"""
CollectiveAccess Table Schema Update Utility.

This script queries the CollectiveAccess GraphQL API server to retrieve the
schema definition (bundles and attributes) for a given database table,
and saves the parsed mapping configuration to "{table_name}-schema.json".
"""

import os
import sys
import json
import tomllib
from graphql_client import send_graphql_query

script_dir = os.path.dirname(os.path.abspath(__file__))
config_file = os.path.join(script_dir, "config", "config.toml")

# Load configuration values for defaults
config_data = {}
if os.path.exists(config_file):
    try:
        with open(config_file, 'rb') as f:
            config_data = tomllib.load(f)
    except Exception:
        pass

# The base URL of the CollectiveAccess GraphQL API service server
API_SERVER = config_data.get("api_server", "https://museum.uwinnipeg.ca/ca/service")

# The default target database table name (e.g. ca_objects)
TABLE_NAME = config_data.get("table_name", "ca_objects")

def main():
    """
    Main entry point. Queries the GraphQL schema endpoint for the target table
    and saves the formatted JSON result to a table-specific schema file.

    Usage:
        python update-table-schema.py ["<table_name>"]
            - table_name: Target database table name (default: ca_objects)

    Expected Outputs:
        Writes a JSON mapping file at f"{table_name}-schema.json" containing all table bundle definitions.
    """
    # Get configurable table name
    table_name = sys.argv[1] if len(sys.argv) > 1 else TABLE_NAME
    print(f"Retrieving schema for table: {table_name}")

    # Run schema query to get schema
    print("Retrieving table schema...")
    schema_payload = f"""query {{
      bundles(table: "{table_name}") {{
        bundles {{
              name,
              code,
              description,
              type,
              dataType,
              list,
              subelements {{
                      name,
                      code,
                      type,
                      dataType,
                      list
              }}
        }}
      }}
}}"""
    schema_response = send_graphql_query(API_SERVER, "Schema", schema_payload)
    
    # Format and save schema
    output_data = {
        "ok": True,
        "data": schema_response.get("data", {})
    }
    
    output_dir = os.path.join(script_dir, "data")
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f"{table_name}-schema.json")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=4, ensure_ascii=False)
        
    print(f"Schema successfully updated and saved to: {output_file}")

if __name__ == "__main__":
    main()