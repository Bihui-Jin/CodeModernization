import json
import os
import re
import html
import random
import inspect
from tqdm import tqdm
import nbformat
from nbformat.v4 import new_notebook, new_markdown_cell, new_code_cell

parent = '/home/b27jin/mle-bench-internal/fetch/competitions'
output_path = "baseline/nltk_corpora.txt"

def read_html_content(file_path, nb=None):
    """Read the content of an HTML file and append code cells to notebook if provided"""
    with open(file_path, "r", encoding="utf-8") as file:
        content = file.read()
        
        # Find all code blocks with highlight hl-ipython3 class
        highlight_blocks = re.findall(r'<div class="highlight hl-ipython3">(.*?)</div>', content, re.DOTALL)
        
        # Process all input areas as before for backward compatibility
        input_areas = re.findall(r'<div class="input_area">(.*?)</div>', content, re.DOTALL)
        input_areas = "".join(input_areas) if input_areas else ""
        input_areas = re.sub(r' *<pre>', '<pre>', input_areas)
        
        # If notebook object provided, add each code block as a cell
        if nb is not None:
            # nb.cells.append(new_code_cell('%pip install Unidecode monai ttach optuna optuna-integration'))
            # nb.cells.append(new_code_cell('import pandas as pd\nfrom pathlib import Path'))
            for block in highlight_blocks:
                # Extract code from the highlight block
                code_match = re.search(r'<pre>(.*?)</pre>', block, re.DOTALL)
                if code_match:
                    # Clean up the code
                    code_text = html.unescape(code_match.group(1))
                    raw_code = assemble_code_regex(code_text)
                    nb.cells.append(new_code_cell(raw_code))
        
        return input_areas
    
def assemble_code_regex(html_snippet: str) -> str:
    """
    Uses a regular expression to remove HTML tags from the snippet and unescapes HTML entities.
    """
    # Unescape any HTML entities (if present)
    code = html.unescape(html_snippet)
    # Remove all HTML tags using regex
    code = re.sub(r'</?[a-zA-Z][^>]*>', '', code)

    return code

def extract_nltk_downloads(nb):
    """Return a list of all package names passed to nltk.download in the notebook."""

    downloads = set()
    # matches nltk.download('pkg') or nltk.download("pkg")
    pattern = re.compile(r"nltk\.download\(\s*['\"]([^'\"]+)['\"]")

    for cell in nb.get('cells', []):
        if cell.get('cell_type') != 'code':
            continue
        src = "".join(cell.get('source', []))
        for m in pattern.finditer(src):
            downloads.add(m.group(1))

    return downloads

# 1. Load the JSON data
with open("kernel.json", "r", encoding="utf-8") as f:
    data = json.load(f)

# 2. Flatten & filter entries
filtered = []
for comp, files in tqdm(data.items(), total=len(data),
        desc="Competitions",
        position=0):
    for fname, info in tqdm(files.items(), total=len(files),
        desc=f"submissions to {comp}",
        leave=False,
        position=1):
        if "ps" in info and info['runtime'] <= 600 and len(info['datasets'])<=1 and "R" not in info and 'nltk' in info['api'] :
            # keep a reference to competition and filename if you need them
            filtered.append((comp, fname))

print(f"Total filtered entries w/ using nltk: {len(filtered)}")

corpora = set()

for comp, fname in tqdm(filtered):
    path = os.path.join(parent, comp, 'html', fname)
    
    # Create notebook first
    nb = new_notebook()
    content = read_html_content(path, nb)
    raw_code = assemble_code_regex(content)
    nb.cells.append(new_code_cell(raw_code))

    pkg = extract_nltk_downloads(nb)


    corpora.update(pkg)

with open(output_path, "w", encoding="utf-8") as f:
        for pkg in corpora:
            f.write(f"{pkg}\n")
    
print(f"Successfully saved {len(corpora)} unique corpora to {output_path}")