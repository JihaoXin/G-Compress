#!/usr/bin/env python3
"""Convert report.md to PDF with mermaid support."""

import markdown
import base64
import re
from weasyprint import HTML
from pathlib import Path

def convert_mermaid_to_img(md_content: str) -> str:
    """Convert mermaid code blocks to images using mermaid.ink."""

    # Pattern to match mermaid code blocks
    mermaid_pattern = r'```mermaid\s*\n(.*?)\n```'

    def replace_mermaid(match):
        mermaid_code = match.group(1).strip()
        # Encode to base64 for mermaid.ink
        encoded = base64.urlsafe_b64encode(mermaid_code.encode('utf-8')).decode('utf-8')
        img_url = f'https://mermaid.ink/img/{encoded}'
        return f'![mermaid diagram]({img_url})'

    return re.sub(mermaid_pattern, replace_mermaid, md_content, flags=re.DOTALL)

# Read the markdown file
md_path = Path('/home/xinj/G-Compress/report.md')
md_content = md_path.read_text(encoding='utf-8')

# Convert mermaid blocks to images
md_content = convert_mermaid_to_img(md_content)

# Convert markdown to HTML with extensions
html_content = markdown.markdown(
    md_content,
    extensions=['tables', 'fenced_code', 'codehilite', 'md_in_html']
)

# Create a full HTML document with CSS styling
full_html = f'''
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        @page {{
            size: A4;
            margin: 2cm;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            max-width: 100%;
            margin: 0 auto;
            padding: 0;
            color: #333;
        }}
        h1 {{
            color: #2c3e50;
            border-bottom: 2px solid #3498db;
            padding-bottom: 10px;
            font-size: 1.8em;
        }}
        h2 {{
            color: #34495e;
            margin-top: 30px;
            font-size: 1.4em;
        }}
        h3 {{
            color: #7f8c8d;
            font-size: 1.2em;
        }}
        code {{
            background-color: #f4f4f4;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
        }}
        pre {{
            background-color: #f4f4f4;
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
            font-size: 0.85em;
        }}
        pre code {{
            background-color: transparent;
            padding: 0;
        }}
        img {{
            max-width: 100%;
            height: auto;
            display: block;
            margin: 20px auto;
        }}
        hr {{
            border: none;
            border-top: 1px solid #ddd;
            margin: 30px 0;
        }}
        small {{
            color: #666;
            font-size: 0.9em;
        }}
        table {{
            border-collapse: collapse;
            width: 100%;
            margin: 20px 0;
        }}
        th, td {{
            border: 1px solid #ddd;
            padding: 8px;
            text-align: left;
        }}
        th {{
            background-color: #f4f4f4;
        }}
        strong {{
            color: #2c3e50;
        }}
        ul, ol {{
            margin: 10px 0;
            padding-left: 25px;
        }}
        li {{
            margin: 5px 0;
        }}
    </style>
</head>
<body>
{html_content}
</body>
</html>
'''

# Convert to PDF
output_path = '/home/xinj/G-Compress/report.pdf'
HTML(string=full_html, base_url=str(md_path.parent)).write_pdf(output_path)

print(f'PDF generated: {output_path}')
