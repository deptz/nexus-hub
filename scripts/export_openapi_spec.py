#!/usr/bin/env python3
"""Export OpenAPI specification to a file for frontend development."""

import json
import sys
import os
from pathlib import Path

# Add parent directory to path to import app
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.main import app

def export_openapi_spec(output_path: str = "openapi.json"):
    """Export OpenAPI specification to a JSON file."""
    # Get the OpenAPI schema
    openapi_schema = app.openapi()
    
    # Write to file
    output_file = Path(output_path)
    with open(output_file, "w") as f:
        json.dump(openapi_schema, f, indent=2)
    
    print(f"✅ OpenAPI specification exported to: {output_file.absolute()}")
    print(f"   File size: {output_file.stat().st_size:,} bytes")
    print(f"\n📋 You can use this file with:")
    print(f"   - OpenAPI Generator: https://openapi-generator.tech/")
    print(f"   - Swagger Codegen: https://swagger.io/tools/swagger-codegen/")
    print(f"   - Postman: Import the JSON file")
    print(f"   - Insomnia: Import the JSON file")
    print(f"   - Frontend code generators (TypeScript, React, etc.)")
    
    return output_file

if __name__ == "__main__":
    # Default output path
    output_path = os.getenv("OPENAPI_OUTPUT", "openapi.json")
    
    # Allow override via command line
    if len(sys.argv) > 1:
        output_path = sys.argv[1]
    
    export_openapi_spec(output_path)

