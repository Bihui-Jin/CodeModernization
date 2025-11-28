import json
import datetime
from tqdm import tqdm
from collections import Counter
from nbformat.v4 import new_notebook, new_code_cell
import os
import re
import html

parent = '/home/b27jin/mle-bench-internal/fetch/competitions'

with open("kernel.json", "r", encoding="utf-8") as f:
    kernel_content = json.load(f)

with open("apiDowngrade/python_versions.json", "r", encoding="utf-8") as f:
    python_versions = json.load(f)

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
            nb.cells.append(new_code_cell('import pandas as pd\nfrom pathlib import Path'))
            for block in highlight_blocks:
                # Extract code from the highlight block
                code_match = re.search(r'<pre>(.*?)</pre>', block, re.DOTALL)
                if code_match:
                    # Clean up the code
                    code_text = html.unescape(code_match.group(1))
                    raw_code = assemble_code_regex(code_text)
                    # code = inspect.cleandoc(raw_code)
                    nb.cells.append(new_code_cell(raw_code))
        
        return nb
    
def assemble_code_regex(html_snippet: str) -> str:
    """
    Uses a regular expression to remove HTML tags from the snippet and unescapes HTML entities.
    """
    # Unescape any HTML entities (if present)
    code = html.unescape(html_snippet)
    # Remove all HTML tags using regex
    code = re.sub(r'</?[a-zA-Z][^>]*>', '', code)

    return code

def classify_notebook(nb):
    """
    Robustly discern if the code is written in python 2 syntax or python 3.
    Returns '2', '3', or 'unknown'.
    """
    py2_hits = 0
    py3_hits = 0

    # Regex patterns for Python 2 specific syntax
    py2_patterns = [
        r'(^|[^a-zA-Z0-9_])print\s+["\']',      # print "string" (no parentheses)
        r'(^|[^a-zA-Z0-9_])print\s+[\w]+',      # print var (no parentheses)
        r'\bxrange\b',                          # xrange vs range
        r'\braw_input\b',                       # raw_input vs input
        r'\bunicode\b',                         # unicode type
        r'\blong\b',                            # long type
        r'\bbasestring\b',                      # basestring type
        r'\.iteritems\(',                       # dict.iteritems()
        r'except\s+\w+\s*,\s*\w+',              # except Exception, e
        r'from\s+__future__\s+import\s+division', # __future__ imports common in Py2
    ]
    # Regex patterns for Python 3 specific syntax
    py3_patterns = [
        r'\bprint\s*\(',                        # print "string" with parentheses
        r'\bf["\']',                            # f-strings (Py 3.6+)
        r'\basync\s+def\b',                     # async/await (Py 3.5+)
        r'\bawait\b',
        r'\bnonlocal\b',                        # nonlocal keyword
        r'\btyping\b',                          # typing module
        r'\)\s*->\s*[A-Za-z_]',                 # function return annotations
        r'\byield\s+from\b',                    # yield from (Py 3.3+)
    ]
    for cell in nb.cells:
        if cell.get('cell_type') == 'code':
            src = ''.join(cell.get('source', ''))
            if not src.strip():
                continue

            for p in py2_patterns:
                if re.search(p, src):
                    py2_hits += 1
            for p in py3_patterns:
                if re.search(p, src):
                    py3_hits += 1

    if py2_hits == 0 and py3_hits == 0:
        return 'unknown'
    if py2_hits > py3_hits:
        return '2'
    if py3_hits >= py2_hits: # Default to 3 if tied, as it's more likely for recent files from the distribution
        return '3'
    return 'unknown'

# Convert python_versions to datetime objects for comparison
python_versions_dt = {
    version: datetime.datetime.strptime(date, "%Y-%m-%d")
    for version, date in python_versions.items()
}

if __name__ == "__main__":
    updated_count = 0
    no_match_count = 0
    python_version_counts = Counter()

    for compt, files in tqdm(
            kernel_content.items(),
            total=len(kernel_content),
            desc="Competitions",
            position=0):
            for fname, script_meta in tqdm(
                files.items(),
                total=len(files),
                desc=f"Processing {compt}",
                leave=False,
                position=1
            ):
                if "ps" in script_meta and script_meta['runtime'] <= 600 and len(script_meta['datasets'])<=1 and "R" not in script_meta:
                    # Extract dependencies
                    path = os.path.join(parent, compt, 'html', fname)
                    # Create notebook first
                    nb = new_notebook()
                    # Pass notebook to read_html_content to add cells directly
                    nb = read_html_content(path, nb)
                    detected_major = classify_notebook(nb)

                    # Restrict search space by detected major if known
                    if detected_major == '2':
                        candidate = {v: d for v, d in python_versions_dt.items() if v.startswith('2.')}
                    elif detected_major == '3':
                        candidate = {v: d for v, d in python_versions_dt.items() if v.startswith('3.')}
                    else:
                        candidate = python_versions_dt

                    submission_date = datetime.datetime.strptime(script_meta["datetime"], "%Y-%m-%dT%H:%M:%S.%fZ")

                    # Find the most recent Python version released before submission_date
                    best_version = None
                    best_date = None
                    
                    for version, release_date in candidate.items():
                        if release_date < submission_date:
                            if best_date is None or release_date > best_date:
                                best_date = release_date
                                best_version = version
                    
                    if best_version:
                        script_meta["python"] = best_version
                        script_meta["detected_major"] = detected_major
                        python_version_counts[best_version] += 1
                        updated_count += 1
                    else:
                        no_match_count += 1
                        script_meta["detected_major"] = detected_major
                        print(f"No Python version found for {compt}/{fname} (submission: {submission_date.date()})")
                    
                    
    # Save updated kernel.json
    with open("apiDowngrade/kernel_w_pyVersion.json", "w", encoding="utf-8") as f:
        json.dump(kernel_content, f, indent=4, ensure_ascii=False)

    print(f"\nUpdated {updated_count} scripts with Python versions")
    print(f"No match found for {no_match_count} scripts")

        # Sort by version number (descending)
    sorted_versions = sorted(python_version_counts.items(), 
                            key=lambda x: tuple(map(int, x[0].split('.'))), 
                            reverse=True)
    
    # Generate Markdown output
    markdown_output = []
    markdown_output.append("# Python Version Statistics\n")
    markdown_output.append(f"**Total scripts updated:** {updated_count}  ")
    markdown_output.append(f"**Scripts with no match:** {no_match_count}  ")
    markdown_output.append(f"**Total unique versions:** {len(python_version_counts)}\n")
    
    markdown_output.append("## Python Version Distribution\n")
    markdown_output.append("| Python Version | Count | Percentage |")
    markdown_output.append("|----------------|-------|------------|")
    
    for version, count in sorted_versions:
        percentage = (count / updated_count * 100) if updated_count > 0 else 0
        markdown_output.append(f"| {version} | {count} | {percentage:.2f}% |")
    
    markdown_output.append("")
    
    # Print to console
    print("\n" + "\n".join(markdown_output))
    
    print(f"{'-'*60}")
    print(f"Total unique versions: {len(python_version_counts)}")
    print(f"{'='*60}")


