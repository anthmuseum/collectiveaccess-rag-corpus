"""
CollectiveAccess Unified JSON Schema Generator.

This script reads all table schema files in `data/` subdirectory, compiles a unified list
of properties, and generates a valid JSON Schema file saved to `items/schema.json`.
"""

import os
import glob
import json
import sys
import tomllib

def main():
    """
    Main entry point. Automatically scans the data directory for schema mapping files,
    parses each bundle code to map its datatype, and outputs a unified JSON Schema configuration.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(script_dir, "data")
    
    # Load configuration to find the items directory
    config_file = os.path.join(script_dir, "config", "config.toml")
    config_data = {}
    if os.path.exists(config_file):
        try:
            with open(config_file, 'rb') as f:
                config_data = tomllib.load(f)
        except Exception:
            pass
            
    output_dir_setting = config_data.get("html_output_dir", "items")
    if not os.path.isabs(output_dir_setting):
        output_dir = os.path.normpath(os.path.join(script_dir, output_dir_setting))
    else:
        output_dir = output_dir_setting
        
    os.makedirs(output_dir, exist_ok=True)
    schema_output_path = os.path.join(output_dir, "schema.json")
    
    schema_pattern = os.path.join(data_dir, "*-schema.json")
    schema_files = glob.glob(schema_pattern)
    
    if not schema_files:
        print(f"Error: No schema files found in {data_dir}", file=sys.stderr)
        sys.exit(1)
        
    properties = {
        "@context": {
            "type": "object"
        },
        "@id": {
            "type": "string",
            "format": "uri"
        },
        "@type": {
            "type": "string"
        },
        "ca_object_representations.media.large": {
            "title": "Media Large representation",
            "description": "Embedded media representation elements",
            "anyOf": [
                { "type": "string" },
                { "type": "array", "items": { "type": "string" } }
            ]
        },
        "ca_object_representations.media.original.url": {
            "title": "Media Original URL",
            "description": "Direct URL to original media elements",
            "anyOf": [
                { "type": "string", "format": "uri" },
                { "type": "array", "items": { "type": "string", "format": "uri" } }
            ]
        },
        "ca_object_representations.media.icon": {
            "title": "Media Icon representation",
            "description": "Icon representation thumbnail elements",
            "anyOf": [
                { "type": "string" },
                { "type": "array", "items": { "type": "string" } }
            ]
        }
    }
    
    # Process all schema files to extract fields
    for schema_file in sorted(schema_files):
        print(f"Reading schema file: {schema_file}")
        try:
            with open(schema_file, 'r', encoding='utf-8') as f:
                schema_data = json.load(f)
            
            bundles_list = schema_data.get("data", {}).get("bundles", {}).get("bundles", [])
            for b in bundles_list:
                code = b.get("code")
                if not code:
                    continue
                    
                name = b.get("name")
                description = b.get("description")
                data_type = b.get("dataType")
                
                # Determine JSON Schema type mapping
                if data_type in ("INTEGER", "NUMERIC"):
                    scalar_schema = { "type": "number" }
                else:
                    scalar_schema = { "type": "string" }
                    
                # Store or update the property schema
                properties[code] = {
                    "title": name,
                    "description": description or "",
                    "anyOf": [
                        scalar_schema,
                        { "type": "array", "items": scalar_schema }
                    ]
                }
        except Exception as e:
            print(f"Warning: Failed to process schema file {schema_file}: {e}", file=sys.stderr)
            
    # Construct complete JSON Schema
    json_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Unified CollectiveAccess Record Schema",
        "description": "JSON Schema validating compiled CollectiveAccess records",
        "type": "object",
        "properties": properties,
        "required": ["idno"]
    }
    
    with open(schema_output_path, 'w', encoding='utf-8') as f:
        json.dump(json_schema, f, indent=4, ensure_ascii=False)
        
    print(f"Unified JSON Schema successfully created and saved to: {schema_output_path}")

if __name__ == "__main__":
    main()
