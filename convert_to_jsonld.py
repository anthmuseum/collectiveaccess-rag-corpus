"""
Metadata JSON-LD Converter and HTML Generator.

This script compiles raw CollectiveAccess search records into structured
JSON-LD documents mapped according to the GraphQL schema bundle definitions,
and outputs an interactive, Tachyons CSS-styled HTML page complete with hover
definition tooltips and a multi-image slideshow widget.
"""

import os
import json
import uuid
import sys
import html
import tomllib
import re
import glob
# Load configuration values for defaults
script_dir = os.path.dirname(os.path.abspath(__file__))
config_file = os.path.join(script_dir, "config", "config.toml")
config_data = {}
if os.path.exists(config_file):
    try:
        with open(config_file, 'rb') as f:
            config_data = tomllib.load(f)
    except Exception:
        pass

# The base URI prefix namespace used for generating entity @id resource URIs
DEFAULT_BASE_URI = config_data.get("base_uri", "https://museum.uwinnipeg.ca")

# The default target database table name (e.g. ca_objects)
DEFAULT_TABLE_NAME = config_data.get("table_name", "ca_objects")

def escape_safe_html(text, whitelist=None):
    """
    Escapes all HTML tags in a text string except for those in a safe whitelist.

    Variables:
        text (str): The raw text to escape.
        whitelist (list, optional): The list of safe HTML tags to preserve (defaults to standard tags).

    Expected Outputs:
        str: The escaped text string with whitelisted HTML tags restored.
    """
    if whitelist is None:
        whitelist = ["b", "p", "i", "u", "em", "strong", "table", "tr", "td", "th", "ul", "ol", "li", "br"]
    
    escaped = html.escape(str(text))
    
    for tag in whitelist:
        if tag == "br":
            escaped = re.sub(r'&lt;br\s*/?&gt;', '<br />', escaped, flags=re.IGNORECASE)
        else:
            escaped = re.sub(rf'&lt;({tag})&gt;', r'<\1>', escaped, flags=re.IGNORECASE)
            escaped = re.sub(rf'&lt;/({tag})&gt;', r'</\1>', escaped, flags=re.IGNORECASE)
            
    return escaped

def generate_plain_json(json_ld, output_path, html_dir, gcs_bucket):
    """
    Prepares and writes the Google Agent Search ingestion NDJSON record(s) for a database record.
    If original media URLs are present, downloads them to html_dir and appends resource records.

    Variables:
        json_ld (dict): The dictionary containing the processed record properties.
        output_path (str): The file path where the JSON record will be written.
        html_dir (str): Path to the HTML output subdirectory where files are downloaded.
        gcs_bucket (str): GCS bucket name used in generating document URIs.
    """
    import urllib.parse
    import urllib.request
    import mimetypes as py_mimetypes
    
    # 1. Primary Record
    uri = json_ld.get("@id", "")
    uuid_val = uri.rstrip('/').split('/')[-1] if uri else str(uuid.uuid4())
    
    # Extract only type and title
    title = json_ld.get("preferred_labels", "")
    if isinstance(title, list):
        title = "; ".join(map(str, title))
    else:
        title = str(title)
        
    primary_metadata = {
        "type": json_ld.get("@type", "ca_objects"),
        "title": title
    }
    
    primary_record = {
        "id": uuid_val,
        "jsonData": json.dumps(primary_metadata, ensure_ascii=False),
        "content": {
            "mimeType": "text/html",
            "uri": f"gs://{gcs_bucket}/html/{uuid_val}.html"
        }
    }
    
    lines = [json.dumps(primary_record, ensure_ascii=False)]
    
    # 2. Resources/Media Records
    media_urls = json_ld.get("ca_object_representations.media.original.url", [])
    if not isinstance(media_urls, list):
        media_urls = [media_urls] if media_urls else []
        
    media_mimetypes = json_ld.get("ca_object_representations.media.mimetype", [])
    if not isinstance(media_mimetypes, list):
        media_mimetypes = [media_mimetypes] if media_mimetypes else []
        
    media_filenames = json_ld.get("ca_object_representations.media.original_filename", [])
    if not isinstance(media_filenames, list):
        media_filenames = [media_filenames] if media_filenames else []
        
    for i, url in enumerate(media_urls):
        if not url:
            continue
            
        # Resolve mimetype
        mimetype = None
        if i < len(media_mimetypes) and media_mimetypes[i]:
            val = str(media_mimetypes[i])
            if "/" in val and "<" not in val and ">" not in val:
                mimetype = val
        if not mimetype:
            mimetype, _ = py_mimetypes.guess_type(url)
        if not mimetype:
            mimetype = "application/octet-stream"
            
        # Resolve filename
        filename = None
        if i < len(media_filenames) and media_filenames[i]:
            val = str(media_filenames[i])
            if "<" not in val and ">" not in val and "/" not in val and "\\" not in val:
                filename = val
        if not filename:
            filename = os.path.basename(urllib.parse.urlparse(url).path)
        if not filename:
            filename = f"media_{i}"
            
        # Generate media UUID from original URL and mimeType
        media_uuid = uuid.uuid5(uuid.NAMESPACE_URL, f"{url}:{mimetype}")
        
        # Download resource if it doesn't already exist
        dest_path = os.path.join(html_dir, filename)
        download_success = True
        if not os.path.exists(dest_path):
            print(f"Downloading resource: {url} -> {dest_path}")
            try:
                req = urllib.request.Request(
                    url, 
                    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
                )
                with urllib.request.urlopen(req) as response:
                    with open(dest_path, 'wb') as out_file:
                        out_file.write(response.read())
            except Exception as e:
                print(f"Warning: Failed to download resource {url}: {e}", file=sys.stderr)
                download_success = False
                
        if download_success:
            resource_metadata = {
                "represents": uuid_val
            }
            resource_record = {
                "id": str(media_uuid),
                "jsonData": json.dumps(resource_metadata, ensure_ascii=False),
                "content": {
                    "mimeType": mimetype,
                    "uri": f"gs://{gcs_bucket}/html/{filename}"
                }
            }
            lines.append(json.dumps(resource_record, ensure_ascii=False))
            
    # Write all lines to the output file (one per line)
    with open(output_path, 'w', encoding='utf-8') as f:
        for line in lines:
            f.write(line + "\n")

def concatenate_to_ndjson(json_dir, ndjson_path):
    """
    Concatenates all JSON files in the specified directory into a single NDJSON file.
    Reads and writes line-by-line to minimize memory footprint.

    Variables:
        json_dir (str): Path to the directory containing JSON files.
        ndjson_path (str): Path to write the output NDJSON file.
    """
    # Locate all files in the directory
    all_files = glob.glob(os.path.join(json_dir, "*"))
    
    # Filter to get only JSON files and exclude the target NDJSON path and any .ndjson files
    json_files = []
    for filepath in all_files:
        # Exclude if it's the target file or ends with .ndjson
        if os.path.abspath(filepath) == os.path.abspath(ndjson_path):
            continue
        if filepath.lower().endswith(".ndjson"):
            continue
        # Only process .json files
        if filepath.lower().endswith(".json"):
            json_files.append(filepath)
            
    # Sort files to ensure deterministic ordering (e.g. by filename)
    json_files.sort()
    
    with open(ndjson_path, 'w', encoding='utf-8') as outfile:
        for filepath in json_files:
            with open(filepath, 'r', encoding='utf-8') as infile:
                for line in infile:
                    stripped = line.strip()
                    if stripped:
                        outfile.write(stripped + "\n")
                        
    print(f"NDJSON output successfully generated and saved to: {ndjson_path}")

def convert_to_jsonld(record_input, schema_path, base_uri=None):
    """
    Converts a database search record structure to a valid JSON-LD representation.

    Variables:
        record_input (str or dict): The filepath to the JSON record, or a preloaded
            record dictionary directly containing record attributes (id, idno, bundles).
        schema_path (str): The filepath to the table schema JSON file.
        base_uri (str, optional): The base URI used in generating vocabularies
            and deterministic UUIDs (defaults to 'https://museum.uwinnipeg.ca').

    Expected Outputs:
        dict: A dictionary containing the structured JSON-LD data.
    """
    if base_uri is None:
        base_uri = DEFAULT_BASE_URI

    # Load schema
    with open(schema_path, 'r', encoding='utf-8') as f:
        schema_data = json.load(f)
    
    # Map bundle codes to their schema definition
    bundles_list = schema_data.get("data", {}).get("bundles", {}).get("bundles", [])
    schema_map = {}
    for b in bundles_list:
        code = b.get("code")
        if code:
            schema_map[code] = {
                "dataType": b.get("dataType"),
                "type": b.get("type"),
                "name": b.get("name")
            }
            
    # Load record
    if isinstance(record_input, str):
        with open(record_input, 'r', encoding='utf-8') as f:
            record = json.load(f)
    else:
        record = record_input
        
    record_id = record.get("id")
    table_name = record.get("table", "ca_objects")
    
    # Generate UUID by concatenating base_uri, table_name, and record_id
    record_uuid = uuid.uuid5(uuid.NAMESPACE_URL, f"{base_uri}/{table_name}/{record_id}")
    
    # Start building JSON-LD
    json_ld = {
        "@context": {
            "@vocab": f"{base_uri}/schema#",
            "id": "@id",
            "type": "@type"
        },
        "@id": f"{base_uri}/items/{record_uuid}",
        "@type": table_name
    }
    
    # Process bundles
    for bundle in record.get("bundles", []):
        code = bundle.get("code")
        name = bundle.get("name")
        values = bundle.get("values", [])
        
        if not code:
            continue
            
        # Strip table prefix if present (e.g., "ca_objects.preferred_labels" -> "preferred_labels")
        prefix = f"{table_name}."
        clean_code = code
        if code.startswith(prefix):
            clean_code = code[len(prefix):]
            
        # Get schema definition
        schema_def = schema_map.get(clean_code, {})
        data_type = schema_def.get("dataType")
        schema_type = schema_def.get("type")
        
        processed_values = []
        for val_obj in values:
            val = val_obj.get("value")
            if val is None or val == "":
                continue
                
            # Convert values based on datatype
            if data_type in ("INTEGER", "NUMERIC"):
                # Check if it can be represented as int or float
                try:
                    if isinstance(val, str):
                        # Strip any spaces
                        val_str = val.strip()
                        if '.' in val_str:
                            val = float(val_str)
                        else:
                            val = int(val_str)
                except ValueError:
                    pass
            elif isinstance(val, str):
                val = val.strip()
                # Split lists/labels by semicolon if appropriate
                if schema_type in ("PREFERRED_LABEL", "NONPREFERRED_LABEL"):
                    if ";" in val:
                        parts = [p.strip() for p in val.split(";") if p.strip()]
                        processed_values.extend(parts)
                        continue
            
            processed_values.append(val)
            
        if not processed_values:
            continue
            
        # If single value, store as scalar; if multiple, store as list
        if len(processed_values) == 1:
            json_ld[clean_code] = processed_values[0]
        else:
            json_ld[clean_code] = processed_values

    return json_ld

def main():
    """
    Main entry point. Loads configurations, reads search items from the configured
    input file, and iterates through each item to write corresponding JSON-LD and HTML pages.

    Usage:
        python convert_to_jsonld.py <table_name> [mode]
    
    Arguments:
        table_name: Target database table name (default: ca_objects)
        mode: Generation mode: "both", "json-ld+html", or "ndjson" (default: both)


    """
    # Resolve file paths relative to this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Determine table name from command-line argument if provided, else default table name
    table_name = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TABLE_NAME
    
    # Determine generation mode from command-line argument if provided, else default to "both"
    mode = sys.argv[2].lower() if len(sys.argv) > 2 else "both"
    if mode not in ["both", "json-ld+html", "ndjson"]:
        print(f"Error: Invalid mode '{mode}'. Choose from 'both', 'json-ld+html', 'ndjson'.", file=sys.stderr)
        sys.exit(1)
        
    do_json_ld_html = mode in ["both", "json-ld+html"]
    do_ndjson = mode in ["both", "ndjson"]
    
    schema_file = os.path.join(script_dir, "data", f"{table_name}-schema.json")
    config_file = os.path.join(script_dir, "config", "config.toml")
    
    # Load config to get output directory and GCS bucket name
    if os.path.exists(config_file):
        with open(config_file, 'rb') as f:
            config_data = tomllib.load(f)
    else:
        config_data = {}
    output_dir_setting = config_data.get("html_output_dir", "items")
    gcs_bucket = config_data.get("gcs_bucket", "museum-search-bucket")
    
    # Resolve absolute path for output directory if it is relative
    if not os.path.isabs(output_dir_setting):
        output_dir = os.path.normpath(os.path.join(script_dir, output_dir_setting))
    else:
        output_dir = output_dir_setting
        
    os.makedirs(output_dir, exist_ok=True)
    json_dir = os.path.join(output_dir, "json")
    if do_ndjson:
        os.makedirs(json_dir, exist_ok=True)
    html_dir = os.path.join(output_dir, "html")
    if do_json_ld_html:
        os.makedirs(html_dir, exist_ok=True)
    
    items_file = os.path.join(script_dir, "data", f"{table_name}-items.json")
    
    if not os.path.exists(items_file):
        print(f"Error: Items file not found at: {items_file}", file=sys.stderr)
        sys.exit(1)
        
    if not os.path.exists(schema_file):
        print(f"Error: Schema file not found at: {schema_file}", file=sys.stderr)
        sys.exit(1)
        
    print(f"Reading items from: {items_file}")
    print(f"Using schema from: {schema_file}")
    print(f"Output directory is: {output_dir}")
    
    with open(items_file, 'r', encoding='utf-8') as f:
        items_data = json.load(f)
        
    results_list = items_data.get("data", {}).get("search", {}).get("results", [])
    records = []
    for res_wrapper in results_list:
        for rec in res_wrapper.get("result", []):
            records.append(rec)
            
    print(f"Found {len(records)} records to process in mode: {mode}")
    
    for record in records:
        # Default the table name in the record
        record.setdefault("table", table_name)
        
        # Convert to JSON-LD
        result_ld = convert_to_jsonld(record, schema_file)
        
        # Extract UUID for filename
        uri = result_ld.get("@id", "")
        uuid_val = uri.rstrip('/').split('/')[-1] if uri else str(uuid.uuid4())
        
        if do_json_ld_html:
            # Save JSON-LD file
            # jsonld_path = os.path.join(output_dir, f"{uuid_val}.json")
            # with open(jsonld_path, 'w', encoding='utf-8') as f:
            #     json.dump(result_ld, f, indent=2, ensure_ascii=False)
                
            # Save HTML file
            html_path = os.path.join(html_dir, f"{uuid_val}.html")
            generate_html(result_ld, schema_file, html_path)
            
        if do_ndjson:
            # Save Plain JSON file
            plain_json_path = os.path.join(json_dir, f"{uuid_val}.json")
            generate_plain_json(result_ld, plain_json_path, html_dir, gcs_bucket)
            
    if do_ndjson:
        # Compile NDJSON file at the end
        ndjson_path = os.path.join(output_dir, "items.ndjson")
        concatenate_to_ndjson(json_dir, ndjson_path)
        
    print("Batch record conversion completed successfully.")

def generate_html(json_ld, schema_path, output_path):
    """
    Generates a clean HTML page layout representation of the JSON-LD metadata.

    Variables:
        json_ld (dict): The structured JSON-LD dictionary of record attributes.
        schema_path (str): The filepath to the schema mapping file.
        output_path (str): The filepath where the output HTML file should be written.

    Expected Outputs:
        Writes a fully styled Tachyons HTML file to the filepath specified in output_path.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_file = os.path.join(script_dir, "config", "config.toml")
    
    # Load config for header and footer
    with open(config_file, 'rb') as f:
        config = tomllib.load(f)
        
    header_html = config.get("html_header", "<header class=\"pv3 bb b--black-10 mb4\"><h1 class=\"f3 f2-m f1-l fw2 black-90 mv0\">Museum Record</h1></header>")
    footer_html = config.get("html_footer", "<footer class=\"pv4 mt5 bt b--black-10\"><p class=\"f6 gray mv0\">© Museum</p></footer>")
    
    # Load schema metadata
    schema_map = {}
    if os.path.exists(schema_path):
        try:
            with open(schema_path, 'r', encoding='utf-8') as f:
                schema_data = json.load(f)
            bundles_list = schema_data.get("data", {}).get("bundles", {}).get("bundles", [])
            for b in bundles_list:
                code = b.get("code")
                if code:
                    schema_map[code] = {
                        "name": b.get("name"),
                        "description": b.get("description")
                    }
        except Exception as e:
            print(f"Warning: Could not parse schema file: {e}", file=sys.stderr)
            
    # Get a friendly title
    title = json_ld.get("preferred_labels", "") or json_ld.get("idno", "Museum Record")
    if isinstance(title, list):
        title = ", ".join(map(str, title))
        
    # Pretty-print raw JSON-LD for script tag
    raw_jsonld_str = json.dumps(json_ld, indent=2, ensure_ascii=False)
    
    # Extract media items
    media_large = json_ld.get("ca_object_representations.media.large", "")
    media_original = json_ld.get("ca_object_representations.media.original.url", "")
    media_icon = json_ld.get("ca_object_representations.media.icon", "")
    media_original_filename = json_ld.get("ca_object_representations.media.original_filename", "")
    
    def to_list_of_strings(val):
        if not val:
            return []
        if isinstance(val, list):
            return [str(item) for item in val if item]
        return [str(val)]
        
    media_large_list = to_list_of_strings(media_large)
    media_original_list = to_list_of_strings(media_original)
    media_icon_list = to_list_of_strings(media_icon)
    media_original_filename_list = to_list_of_strings(media_original_filename)
    
    media_html = ""
    if len(media_large_list) > 1:
        slides_html_list = []
        icons_html_list = []
        for i, img_tag in enumerate(media_large_list):
            orig_url = media_original_list[i] if i < len(media_original_list) else ""
            
            # Resolve relative filename
            filename = None
            if i < len(media_original_filename_list) and media_original_filename_list[i]:
                val = str(media_original_filename_list[i])
                if "<" not in val and ">" not in val and "/" not in val and "\\" not in val:
                    filename = val
            if not filename and orig_url:
                import urllib.parse
                filename = os.path.basename(urllib.parse.urlparse(orig_url).path)
            if not filename:
                filename = f"media_{i}"
                
            if "<img" in img_tag.lower() and filename:
                slide_content = f'<a href="{filename}">{img_tag}</a>'
            else:
                slide_content = img_tag
                
            display_style = "block" if i == 0 else "none"
            slides_html_list.append(f"""        <div class="slideshow-slide" id="slide-{i}" style="display: {display_style};">
            {slide_content}
        </div>""")
            
            if i < len(media_icon_list):
                icon_tag = media_icon_list[i]
                border_color = "#357edd" if i == 0 else "transparent"
                opacity_val = "1" if i == 0 else "0.5"
                icons_html_list.append(f"""        <button type="button" class="slideshow-dot pointer ba pa1 bg-transparent" id="dot-{i}" onclick="showSlide({i})" style="border: 2px solid {border_color}; opacity: {opacity_val}; border-radius: 4px; transition: all 0.2s ease; margin: 0 4px; padding: 2px;">
            {icon_tag}
        </button>""")
                
        slides_html = "\n".join(slides_html_list)
        icons_html = "\n".join(icons_html_list)
        
        media_html = f"""<div class="mb4 tc mw7 center">
    <div class="slideshow-container bg-near-white pa2 br2 relative overflow-hidden" style="min-height: 200px; display: flex; align-items: center; justify-content: center;">
{slides_html}
    </div>
    <div class="mt3 flex justify-center items-center flex-wrap">
{icons_html}
    </div>
</div>"""
    elif len(media_large_list) == 1:
        img_tag = media_large_list[0]
        orig_url = media_original_list[0] if media_original_list else ""
        
        # Resolve relative filename
        filename = None
        if media_original_filename_list and media_original_filename_list[0]:
            val = str(media_original_filename_list[0])
            if "<" not in val and ">" not in val and "/" not in val and "\\" not in val:
                filename = val
        if not filename and orig_url:
            import urllib.parse
            filename = os.path.basename(urllib.parse.urlparse(orig_url).path)
        if not filename:
            filename = "media_0"
            
        if "<img" in img_tag.lower() and filename:
            media_html = f'<div class="mb4 tc"><a href="{filename}">{img_tag}</a></div>'
        else:
            media_html = f'<div class="mb4 tc">{img_tag}</div>'

    # Prepare properties for the table
    table_rows = []
    
    keys_to_exclude = [
        "@id", "@type", "@context",
        "ca_object_representations.media.large",
        "ca_object_representations.media.original.url",
        "ca_object_representations.media.icon"
    ]
    sorted_keys = sorted([k for k in json_ld.keys() if k not in keys_to_exclude])
    
    # Combined list of keys to display: tuple of (key, label, description)
    display_keys = []
    if "@id" in json_ld:
        display_keys.append(("@id", "Resource URI (@id)", "The unique identifier of this resource"))
    if "@type" in json_ld:
        display_keys.append(("@type", "Class Type (@type)", "The class type of this resource"))
        
    for k in sorted_keys:
        schema_def = schema_map.get(k, {})
        label = schema_def.get("name")
        description = schema_def.get("description")
        
        if not label:
            # Fallback to formatting the key if not found in schema
            label = k.replace("_", " ").title()
            
        display_keys.append((k, label, description))
        
    for index, (key, label, description) in enumerate(display_keys):
        val = json_ld[key]
        
        # Format the value nicely
        if isinstance(val, list):
            val_str = ", ".join(map(str, val))
        else:
            val_str = str(val)
            
        # Format label with hover description if available
        if description:
            escaped_label = f'<span style="border-bottom: 1px dotted #777; cursor: help;" title="{html.escape(description)}">{html.escape(label)}</span>'
        else:
            escaped_label = html.escape(label)
            
        escaped_val = escape_safe_html(val_str)
        
        # Add hyperlinking for the @id URI
        if key == "@id":
            escaped_val = f'<a href="{escaped_val}" class="link blue dim">{escaped_val}</a>'
            
        # Alternating row background colors for zebra striping
        row_bg = "bg-near-white" if index % 2 == 1 else "bg-white"
        
        row_html = f"""                    <tr class="{row_bg}">
                        <td class="pv3 ph3 bb b--black-10 fw6 w-30">{escaped_label}</td>
                        <td class="pv3 ph3 bb b--black-10 w-70">{escaped_val}</td>
                    </tr>"""
        table_rows.append(row_html)
        
    table_rows_str = "\n".join(table_rows)
    
    # Conditional slideshow javascript definition
    has_slideshow = len(media_large_list) > 1
    if has_slideshow:
        script_html = """    <script>
        function showSlide(index) {
            var slides = document.querySelectorAll('.slideshow-slide');
            for (var i = 0; i < slides.length; i++) {
                slides[i].style.display = 'none';
            }
            var activeSlide = document.getElementById('slide-' + index);
            if (activeSlide) {
                activeSlide.style.display = 'block';
            }
            
            var dots = document.querySelectorAll('.slideshow-dot');
            for (var i = 0; i < dots.length; i++) {
                dots[i].style.borderColor = 'transparent';
                dots[i].style.opacity = '0.5';
            }
            var activeDot = document.getElementById('dot-' + index);
            if (activeDot) {
                activeDot.style.borderColor = '#357edd';
                activeDot.style.opacity = '1';
            }
            
            var container = document.querySelector('.slideshow-container');
            if (container) {
                container.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }
        }
    </script>
"""
    else:
        script_html = ""
    
    # Full HTML template with f5 font size for table
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(str(title))}</title>
    <link rel="stylesheet" href="https://unpkg.com/tachyons@4.12.0/css/tachyons.min.css"/>
    <script type="application/ld+json">
{raw_jsonld_str}
    </script>
{script_html}</head>
<body class="avenir mw8 center pa3 pa4-ns bg-white black-90 f5">
    {header_html}
    
    <main class="pv3">
        {media_html}
        <div class="overflow-auto">
            <table class="f5 w-100 collapse ba b--black-10">
                <thead>
                    <tr class="bg-black-10">
                        <th class="fw6 tl pv3 ph3 bb b--black-20 w-30">Metadata Property</th>
                        <th class="fw6 tl pv3 ph3 bb b--black-20 w-70">Value</th>
                    </tr>
                </thead>
                <tbody class="lh-copy">
{table_rows_str}
                </tbody>
            </table>
        </div>
    </main>
    
    {footer_html}
</body>
</html>
"""
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"HTML output successfully generated and saved to: {output_path}")

if __name__ == "__main__":
    main()
