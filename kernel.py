from tqdm import tqdm
import re,os,glob, time
import datetime
import ast
import html
import json
import warnings
import tempfile
import nbformat
import subprocess
from pathlib import Path
from nbformat.v4 import new_notebook, new_code_cell
from multiprocessing import Pool, Manager, RLock
import multiprocessing
warnings.filterwarnings("ignore", category=SyntaxWarning)

def init_pool(l):
    """Initialize the worker process with a shared lock for tqdm."""
    tqdm.set_lock(l)

def get_folders(base_path):
    """Get the folder names under the base path"""
    return [f for f in os.listdir(base_path) if os.path.isdir(os.path.join(base_path, f))]

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


def time_to_seconds(text):
    """
    Extracts hours, minutes, and seconds from a text and converts them to seconds.
    Expected formats are, for example, "4s", "1m 54s", or "1h 59m 59s".
    """
    # The regex looks for optional hours and minutes, and mandatory seconds.
    time_pattern = r'(?:(?P<h>\d+)\s*h)?\s*(?:(?P<m>\d+)\s*m)?\s*(?P<s>\d+)\s*s'
    match = re.search(time_pattern, text)
    if match:
        h = int(match.group('h')) if match.group('h') is not None else 0
        m_val = int(match.group('m')) if match.group('m') is not None else 0
        s = int(match.group('s'))
        return h * 3600 + m_val * 60 + s
    return None

def process_competition(args):
    """Process a single competition"""
    competi, parent = args
    entity = {competi: {}}
    
    # Get worker ID for tqdm positioning (usually 1-based index for Pool workers)
    worker_id = multiprocessing.current_process()._identity[0]
    
    files = glob.glob(os.path.join(parent, competi, 'meta_html','*_C1.html'))
    for file in tqdm(files, desc=f"Worker {worker_id}: {competi}", position=worker_id, leave=False):
        entity[competi][file.split("/")[-1]] = {}
        with open(os.path.join(parent, competi, 'meta_html',file.split("/")[-1]), "r", encoding="utf-8") as fp:
            content = fp.read()
            # Submission Year
            pattern = r'<span [^>]*title="([A-Z][a-z]{2} [A-Z][a-z]{2} \d{2} \d{4} \d{2}:\d{2}:\d{2} GMT[+-]\d{4} \([^"]+\))"'
            date = re.findall(pattern, content, re.DOTALL)[0]
            # print(date)
            date_str = date.split(" (")[0].replace("GMT", "")
            # print(date_str)
            dt = datetime.datetime.strptime(date_str, "%a %b %d %Y %H:%M:%S %z")

            entity[competi][file.split("/")[-1]]['year'] = dt.year
            entity[competi][file.split("/")[-1]]['month'] = dt.month
            entity[competi][file.split("/")[-1]]['date'] = dt.day
            entity[competi][file.split("/")[-1]]['datetime'] = dt.astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            
            # Find Private Score     
            pattern = r'<p class="sc-gQaihK[^"]*">\s*([-\d.]+)\s*</p>'
            matches = re.findall(pattern, content, re.DOTALL)
            # has P.Score
            if matches:
                entity[competi][file.split("/")[-1]]['ps'] =  matches[0]

            # Extract all time blocks (non-greedy match with DOTALL)
            pattern = r'<p\s+class="sc-gQaihK\s+(?:sc-bHbnRu|sc-hKjFaw)\s+bwaGMg\s+(?:hAkjhA|jGRPCU)">(.*?)</p>'
            p_tags = re.findall(pattern, content, re.DOTALL)
            for tag in p_tags:
                seconds = time_to_seconds(tag)
                if seconds is not None:
                    entity[competi][file.split("/")[-1]]['runtime'] =  seconds

            # Extract dependencies
            path = os.path.join(parent, competi, 'html', file.split("/")[-1])
            # Create notebook first
            nb = new_notebook()
            # Pass notebook to read_html_content to add cells directly
            nb = read_html_content(path, nb)

            # If no cells were added, add the whole content as one cell
            if len(nb.cells) != 1:
                file_deps = get_imports_from_file(nb, path=file)
                entity[competi][file.split("/")[-1]]['api'] = list(file_deps)
            else:
                entity[competi][file.split("/")[-1]]['R'] = 1
            

            pattern = r'<p\s+class="sc-gQaihK sc-dyfHgC bwaGMg igmQhu">\s*(.*?)\s*</p>'
            matches = re.findall(pattern, content, flags=re.DOTALL)
            entity[competi][file.split("/")[-1]]['datasets'] =  list(set(matches))
    
    return entity
    
def get_imports_from_file(notebook, path=None):
    """Use pigar to detect dependencies"""
    deps = set()
    with tempfile.TemporaryDirectory() as tmpdir:
        workdir = Path(tmpdir)
        
        with open(workdir / "script.ipynb", "w", encoding="utf-8") as file:
            nbformat.write(notebook, file)
        
        # Retry up to 3 times if pigar times out
        for attempt in range(3):
            try:
                # pigar generate <folder>
                # print("Running pigar...")
                result = subprocess.run(
                    ["pigar", "generate", "--auto-select", tmpdir],
                    # ["pipreqs", "--scan-notebooks", tmpdir],
                    cwd=tmpdir,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    # input="*\n" + "y\n" + "*\n" * 20,
                    input="y\n" * 30,
                )
                # print("Pigar completed.")

                # print("STDOUT:", result.stdout)
                # print("STDERR:", result.stderr)
                # print("Return code:", result.returncode)

                # print(get_folders(tmpdir))
                # Parse requirements.txt output
                req_file = Path(tmpdir) / "requirements.txt"
                # print(req_file.exists())
                if req_file.exists():
                    for line in req_file.read_text().splitlines():
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        pkg = line.split('==')[0].split('>=')[0].split('<=')[0].strip()
                        if pkg:
                            deps.add(pkg)

                    time.sleep(0.5)
                    return deps
                # If execution finished without timeout but no file was created, stop retrying
                break

            except subprocess.TimeoutExpired:
                # If it timed out, loop will continue to next attempt
                if attempt == 2:
                    with open("kernel_timeout.json", "a", encoding="utf-8") as json_file:
                        json_file.write(f"{path}\n")
                continue

            except Exception as e:
                print(f"pigar failed: {e}")
                pass
    
    return deps

if __name__ == '__main__':
    # parent = 'C:\\Users\\b27jin\\Documents\\mle-bench-internal\\fetch\\competitions'
    parent = '/home/b27jin/mle-bench-internal/fetch/competitions'

    # Get all competitions
    competitions = get_folders(parent)
    
    # Prepare arguments for each worker
    args_list = [(comp, parent) for comp in competitions]
    
    # Create a shared lock for tqdm
    # This prevents workers from writing to the terminal simultaneously
    tqdm_lock = RLock()
    tqdm.set_lock(tqdm_lock)

    # Create pool with n workers
    with Pool(processes=32, initializer=init_pool, initargs=(tqdm_lock,)) as pool:
        # Use imap for progress bar
        results = list(tqdm(
            pool.imap(process_competition, args_list),
            total=len(args_list),
            desc="Competitions",
            position=0  # Force main bar to stay at the top
        ))
    
    # Merge all results
    entity = {}
    for result in results:
        entity.update(result)
# entity = {}
# for competi in tqdm(get_folders(parent), desc="Competitions"):
# # for competi in dev:
#     entity[competi] = {}
#     i=1
#     for file in tqdm(glob.glob(os.path.join(parent, competi, 'meta_html','*_C1.html')), desc=competi, leave=False):
#         entity[competi][file.split("/")[-1]] = {}
#         with open(os.path.join(parent, competi, 'meta_html',file.split("/")[-1]), "r", encoding="utf-8") as fp:
#             content = fp.read()
#             # Submission Year
#             pattern = r'<span [^>]*title="([A-Z][a-z]{2} [A-Z][a-z]{2} \d{2} \d{4} \d{2}:\d{2}:\d{2} GMT[+-]\d{4} \([^"]+\))"'
#             date = re.findall(pattern, content, re.DOTALL)[0]
#             # print(date)
#             date_str = date.split(" (")[0].replace("GMT", "")
#             # print(date_str)
#             dt = datetime.datetime.strptime(date_str, "%a %b %d %Y %H:%M:%S %z")

#             entity[competi][file.split("/")[-1]]['year'] = dt.year
#             entity[competi][file.split("/")[-1]]['month'] = dt.month
#             entity[competi][file.split("/")[-1]]['date'] = dt.day
#             entity[competi][file.split("/")[-1]]['datetime'] = dt.astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            
#             # Find Private Score     
#             pattern = r'<p class="sc-gQaihK[^"]*">\s*([-\d.]+)\s*</p>'
#             matches = re.findall(pattern, content, re.DOTALL)
#             # has P.Score
#             if matches:
#                 entity[competi][file.split("/")[-1]]['ps'] =  matches[0]

#             # Extract all time blocks (non-greedy match with DOTALL)
#             pattern = r'<p\s+class="sc-gQaihK\s+(?:sc-bHbnRu|sc-hKjFaw)\s+bwaGMg\s+(?:hAkjhA|jGRPCU)">(.*?)</p>'
#             p_tags = re.findall(pattern, content, re.DOTALL)
#             for tag in p_tags:
#                 seconds = time_to_seconds(tag)
#                 if seconds is not None:
#                     entity[competi][file.split("/")[-1]]['runtime'] =  seconds

#             # Extract dependencies
#             path = os.path.join(parent, competi, 'html', file.split("/")[-1])
#             # Create notebook first
#             nb = new_notebook()
#             # Pass notebook to read_html_content to add cells directly
#             nb = read_html_content(path, nb)

#             # If no cells were added, add the whole content as one cell
#             if len(nb.cells) != 1:
#                 file_deps = get_imports_from_file(nb)
#                 entity[competi][file.split("/")[-1]]['api'] = list(file_deps)
#             else:
#                 entity[competi][file.split("/")[-1]]['R'] = 1
            

#             pattern = r'<p\s+class="sc-gQaihK sc-dyfHgC bwaGMg igmQhu">\s*(.*?)\s*</p>'
#             matches = re.findall(pattern, content, flags=re.DOTALL)
#             entity[competi][file.split("/")[-1]]['datasets'] =  list(set(matches))
        
    # Save the entity dictionary into a JSON file.
    with open("kernel.json", "w", encoding="utf-8") as json_file:
        json.dump(entity, json_file, indent=4, ensure_ascii=False)