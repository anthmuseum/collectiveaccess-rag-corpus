"""
CollectiveAccess Search Results Downloader.

This script executes search queries against the CollectiveAccess GraphQL API server
and paginates through all matching records, pulling specific database bundles configured
by the schema file (while ignoring attributes specified in ignore-fields.txt).
Saves the consolidated results mapping to "{table_name}-items.json".
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

# The default search query keyword term used for record retrieval
SEARCH_TERM = config_data.get("search_term", "felt")

START = 0
LIMIT = 200

def main():
    """
    Main entry point. Automatically loads schema configs and ignore filters, loops
    through all search pages matching the query parameters, aggregates the results,
    and writes them to a consolidated JSON output file.

    Usage:
        python get_items.py ["<table_name>" ["<search_term>" ["<start>" ["<limit>"]]]]
        - table_name: Target database table name (default: ca_objects)
        - search_term: Search query (default: felt)
        - start: Initial page offset (default: 0)
        - limit: Page size (default: 200)

    Expected Outputs:
        Writes a consolidated results file to f"{table_name}-items.json".
    """
    # Extract named variables from command-line arguments
    cmd_table_name = sys.argv[1] if len(sys.argv) > 1 else None
    cmd_search_term = sys.argv[2] if len(sys.argv) > 2 else None
    cmd_start = sys.argv[3] if len(sys.argv) > 3 else None
    cmd_limit = sys.argv[4] if len(sys.argv) > 4 else None

    # Resolve execution parameters
    table_name = cmd_table_name if cmd_table_name is not None else TABLE_NAME
    search_term = cmd_search_term if cmd_search_term is not None else SEARCH_TERM
    start = cmd_start if cmd_start is not None else START
    limit = cmd_limit if cmd_limit is not None else LIMIT
    print(f"Retrieving search for table: {table_name}")
    
    # Load ignored fields
    ignored_fields = set()
    ignore_file = os.path.join(script_dir, "config", "ignore-fields.txt")
    if os.path.exists(ignore_file):
        with open(ignore_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    ignored_fields.add(line)
        print(f"Loaded ignored fields from: {ignore_file}")
        
    # Load schema bundles
    schema_file = os.path.join(script_dir, "data", f"{table_name}-schema.json")
    schema_bundles = []
    if os.path.exists(schema_file):
        try:
            with open(schema_file, 'r', encoding='utf-8') as f:
                schema_data = json.load(f)
            bundles_list = schema_data.get("data", {}).get("bundles", {}).get("bundles", [])
            for b in bundles_list:
                code = b.get("code")
                if code and code not in ignored_fields:
                    # Append prefix if not already present
                    if not code.startswith(f"{table_name}."):
                        full_code = f"{table_name}.{code}"
                    else:
                        full_code = code
                    schema_bundles.append(full_code)
            print(f"Loaded {len(schema_bundles)} bundles from schema: {schema_file}")
        except Exception as e:
            print(f"Warning: Could not read schema file {schema_file}: {e}")
            
    # Combine lists
    bundles =  ["ca_object_representations.media.original.url", 
                "ca_object_representations.media.large",
                "ca_object_representations.media.icon",
                "ca_object_representations.media.original_filename",
                "ca_object_representations.media.mimetype"] + schema_bundles
    bundles_json = json.dumps(bundles)

    # Run search query to get search
    print("Retrieving table search...")
    
    current_start = int(start)
    limit_val = int(limit)
    all_results = []
    total_count = 0
    
    while True:
        print(f"Retrieving search results starting from {current_start} (limit: {limit_val})...")
        search_payload = f"""query {{
            search(
                    table: "{table_name}",
                    search: "{search_term}",
                    bundles: {bundles_json},
                    start: {current_start},
                    limit: {limit_val}
            ) {{
                    table,
                    count,
                    results {{
                            result {{
                              id,
                              idno,
                              bundles {{
                                    code,
                                    values {{
                                            value,
                                    }}                          
                              }}
                            }}
                    }}
            }}
        }}  """
        
        search_response = send_graphql_query(API_SERVER, "Search", search_payload)
        search_data = search_response.get("data", {}).get("search", {})
        if not search_data:
            print("Warning: Received empty search data.", file=sys.stderr)
            break
            
        results = search_data.get("results", [])
        if not results:
            break
            
        all_results.extend(results)
        total_count = search_data.get("count", 0)
        
        print(f"Retrieved {len(results)} items. (Progress: {len(all_results)}/{total_count})")
        
        if len(all_results) >= total_count:
            break
            
        if len(results) < limit_val:
            break
            
        current_start += limit_val
        
    # Format and save search
    output_data = {
        "ok": True,
        "data": {
            "search": {
                "table": table_name,
                "count": total_count if total_count > 0 else len(all_results),
                "results": all_results
            }
        }
    }
    
    output_dir = os.path.join(script_dir, "data")
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f"{table_name}-items.json")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=4, ensure_ascii=False)
        
    print(f"Schema successfully updated and saved to: {output_file}")

if __name__ == "__main__":
    main()