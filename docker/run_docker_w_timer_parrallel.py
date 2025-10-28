import subprocess
import time
import signal
import os
from tqdm import tqdm
from threading import Thread, Event
import queue
import json
import tempfile
import shutil
from pathlib import Path
import re
import select
import threading
import fcntl  # for file locking
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

class NotebookRunner:
    def __init__(self, timeout_seconds):
        self.timeout_seconds = timeout_seconds

    def monitor_execution(self, process, timeout_event, start_event, execution_queue, compt, filename):
        """Monitor Docker process output and detect execution start"""
        execution_started = False
        start_time = None

        try:
            while process.poll() is None and not timeout_event.is_set():
                # Use select to check if there's output available without blocking indefinitely
                ready, _, _ = select.select([process.stderr], [], [], 0.1)
                
                if ready:
                    # Reads stdout line-by-line from the subprocess
                    line = process.stderr.readline()
                    if line:
                        line = line.strip().replace('\r', '').replace('\x1b[K', '')
                        execution_queue.put(('output', line))

                        # print(f"GPU {compt} DOCKER: {line}")

                        # Detect when notebook execution starts (usually the message starts with '[NbClientApp] Executing notebook with kernel:')
                        if not execution_started and any(keyword in line.lower() for keyword in [
                            'executing notebook', 'executing cell', 'executing:', 'running cell', "debugging will proceed", #filename.lower(),
                        ]):
                            execution_started = True
                            start_time = time.time()
                            start_event.set()
                            execution_queue.put(('status', 'Execution started'))
                    
                # Check timeout only after execution has started
                if execution_started and start_time:
                    elapsed_time = time.time() - start_time

                    # Use carriage return to overwrite the same line
                    # print(f"\rElapsed {compt} time: {elapsed_time:.1f}s", end='', flush=True)

                    if elapsed_time > self.timeout_seconds:
                        # print(f"\nTimeout after {elapsed_time:.1f}s")
                        execution_queue.put(('status', f'Timeout after {elapsed_time:.1f}s'))
                        timeout_event.set()
                        break
               
                # time.sleep(0.1)
                
        except Exception as e:
            execution_queue.put(('error', str(e)))
    
    def run_single_notebook(self, docker_command, compt, filename):
        """Run a single notebook with timeout monitoring"""

        # Start a subprocess
        process = subprocess.Popen(
            docker_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            text=True,
            shell=True,
            # Create process group for clean termination so all child processes can be terminated together
            preexec_fn=os.setsid  
        )
        
        # Signaling timeout/start
        timeout_event = Event()
        start_event = Event()
        # Receive output/status messages from the monitor thread
        execution_queue = queue.Queue()
        
        # Launch monitoring thread
        monitor_thread = Thread(
            target=self.monitor_execution,
            args=(process, timeout_event, start_event, execution_queue, compt, filename)
        )
        monitor_thread.daemon = True
        monitor_thread.start()
        
        result = {}
        
        try:
            start_time = None
            abs_start_time = time.time()
            # If the process is still running
            while process.poll() is None:
                # Watch for a timeout signal
                if timeout_event.is_set():
                    # Terminate the entire process group
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                    time.sleep(0.5)
                    if process.poll() is None:
                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    # Update results accordingly
                    result['timeout'] = True
                    actual_elapsed = time.time() - start_time if start_time else self.timeout_seconds
                    result['execution_time'] = actual_elapsed
                    return result
                    
                # Process queue messages
                try:
                    msg_type, msg_data = execution_queue.get_nowait()
                    if msg_type == 'status' and 'Execution started' in msg_data:
                        start_time = time.time()
                except queue.Empty:
                    pass
                
                time.sleep(0.1)
            
            # Process completed
            if start_time:
                execution_time = time.time() - start_time
                result['execution_time'] = execution_time
            # else:
            #     result['execution_time'] = time.time() - abs_start_time

            # result['success'] = process.returncode == 0

            err_out = process.stderr.read() if process.stderr else ""
            if err_out:
                result['error'] = err_out

            stdout_out = process.stdout.read() if process.stdout else ""
            if stdout_out:
                result['detail'] = re.sub(r'\x1b\[[0-9;]*m', '', stdout_out).encode('utf-8').decode('unicode_escape')

        except KeyboardInterrupt:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            result['error'] = 'Interrupted by user'
        except Exception as e:
            result['error'] = str(e)
        
        return result
    

def build_docker_command(k_token, temp_dir, compt, filename, gpu, dst):
    """Build Docker command with only existing directory mounts
    # Run ./zip.sh first (preparation step)
    # Allow docker to accessand mount
    chmod -R a+rw /home/b27jin/.cache
    chmod -R a+rw /home/b27jin/.cache/mle-bench/data
    # Allow to save files in docker
    chmod -R a+rw /home/b27jin/mle-bench-internal/docker-test/scripts
    # Create new docker image with pre pip install via /home/b27jin/mle-bench-internal/docker-test/Dockerfile.base
    """

    optional_paths = {
        f"{dst}/prepared/public/train": "/kaggle/input/train/train",
        f"{dst}/prepared/public/train2": "/kaggle/input/train/train2",
        f"{dst}/prepared/public/train2": "/kaggle/input/train2/train2",
        f"{dst}/prepared/public/train_images": "/kaggle/input/train",
        f"{dst}/prepared/public/train_images": "/kaggle/input/train/train",
        f"{dst}/prepared/public/train_images": "/kaggle/input/train/train_images",
        f"{dst}/prepared/public/train_images": "/kaggle/input/train_images/train_images",
        f"{dst}/prepared/public/test_images": "/kaggle/input/test",
        f"{dst}/prepared/public/test_images": "/kaggle/input/test/test",
        f"{dst}/prepared/public/test_images": "/kaggle/input/test/test_images",
        f"{dst}/prepared/public/test_images": "/kaggle/input/test_images/test_images",
        f"{dst}/prepared/public/test": "/kaggle/input/test/test",
        f"{dst}/prepared/public/test2": "/kaggle/input/test/test2",
        f"{dst}/prepared/public/test2": "/kaggle/input/test2/test2"
    }

    volume_mounts =[]

    # Add only existing directories
    for host_path, container_path in optional_paths.items():
        if os.path.exists(host_path) and os.path.isdir(host_path):
            volume_mounts.append(f'"{host_path}:{container_path}"')

    container_name = f"gpu_{gpu}_{filename.split('.')[0]}"

    cmd = f'docker run --rm -i --name {container_name} --shm-size=30g'
    cmd += f' --cpuset-cpus="{4*gpu},{4*gpu+1},{4*gpu+2},{4*gpu+3}"'
    cmd += f" -e CUDA_VISIBLE_DEVICES={gpu}"
    cmd += f' -e KAGGLE_USER_SECRETS_TOKEN="{k_token}"'
    # cmd += f' -e PYTHONUNBUFFERED=1'  # Ensure immediate output
    # cmd += f' -e PYDEVD_DISABLE_FILE_VALIDATION=1'
    # cmd += f' -e PYTHONFROZEN=0'
    cmd += f' -v {temp_dir}:/kaggle/working'
    cmd += f' -v {dst}/prepared/public:/kaggle/input'
    cmd += f" -v {dst}/prepared/public:/kaggle/input/{compt}"
    # cmd += f' -v {dst}/prepared/public:/kaggle/working'
    cmd += f' -v {dst}/prepared/public:/kaggle/working/{compt}'
    cmd += f' -v {dst}/prepared/public:/kaggle/data'
    cmd += f' -v {dst}/prepared/public:/kaggle/data/{compt}'
    cmd += "".join([f" -v {mount}" for mount in volume_mounts])
    cmd += f" -w /kaggle/working kaggle/customized_{gpu}"
    # cmd += " -lc 'set -euxo pipefail; ls -la; cd ../input/rsna-2022-cervical-spine-fracture-detection; ls'"
    cmd += f" jupyter nbconvert --to notebook --inplace --execute {filename} --ExecutePreprocessor.allow_errors=True --ExecutePreprocessor.timeout=-1"
    # cmd += f" timeout {timeout_seconds*1.1} jupyter nbconvert --to notebook --inplace --execute {filename} --ExecutePreprocessor.allow_errors=True --ExecutePreprocessor.timeout=-1"
    # cmd += f" python -Xfrozen_modules=off -m jupyter nbconvert --to notebook --stdout --execute {filename} --ExecutePreprocessor.allow_errors=True --ExecutePreprocessor.timeout=-1"
    
    return cmd, container_name

def clear_notebook_outputs(notebook_path):
    """Clear all outputs from a Jupyter notebook file"""
    try:
        with open(notebook_path, 'r', encoding='utf-8') as f:
            notebook = json.load(f)
        
        # 1) Clear outputs and execution counts
        for cell in notebook.get('cells', []):
            if cell.get('cell_type') == 'code':
                cell['outputs'] = []
                cell['execution_count'] = None
        
        # 2) Remove first cell if it is exactly our pip‐install stub
        cells = notebook.get('cells', [])
        if cells and cells[0].get('cell_type') == 'code':
            src = cells[0].get('source', '')
            first_src = ''.join(src) if isinstance(src, list) else src
            if '%pip install Unidecode monai ttach optuna optuna-integration' in first_src.strip():
                cells.pop(0)
        notebook['cells'] = cells

        # Save the cleared notebook
        with open(notebook_path, 'w', encoding='utf-8') as f:
            json.dump(notebook, f, indent=2, ensure_ascii=False)
        
        return True
    except Exception as e:
        print(f"Error clearing notebook outputs at {notebook_path}: \n{e}")
        return False


def merge_gpu_results(setting):
    """Merge all GPU-specific JSON files into one final file"""
    merged_results = {}
    
    if setting == "test":
        file_name = 'executable_files_w_timer_parrallel.json' 
        for gpu_id in range(8):
            json_filename = f'executable_files_w_timer_gpu_{gpu_id}.json'
            if os.path.exists(json_filename):
                with open(json_filename, 'r', encoding='utf-8') as f:
                    gpu_results = json.load(f)
                    merged_results.update(gpu_results)
    else:
        file_name = 'executable_files_w_timer_parrallel_full.json'
        for gpu_id in range(8):
            json_filename = f'executable_files_w_timer_gpu_{gpu_id}_full.json'
            if os.path.exists(json_filename):
                with open(json_filename, 'r', encoding='utf-8') as f:
                    gpu_results = json.load(f)
                    merged_results.update(gpu_results)

        with open("executable_files_w_timer_parrallel.json", 'r', encoding='utf-8') as f:
                gpu_results = json.load(f)
                merged_results.update(gpu_results)
    
    # Write merged results
    with open(file_name, 'w', encoding='utf-8') as f:
        json.dump(dict(sorted(merged_results.items())), f, indent=2, ensure_ascii=False)

    print(f"Merged results from {len(merged_results)} entities")



def split_competitions_balanced(b, c, num_groups=8):
    """
    More balanced splitting using dynamic programming approach
    """
    # Calculate total times
    competitions = []
    for comp in b.keys():
        if comp in c:
            total_time = b[comp] * c[comp]
            competitions.append((comp, total_time))
    
    # Sort by total time
    competitions.sort(key=lambda x: x[1], reverse=True)
    
    # Initialize groups
    groups = [[] for _ in range(num_groups)]
    group_totals = [0.0] * num_groups
    
    # For better balance, consider multiple assignment options for each competition
    for comp, total_time in competitions:
        # Find the group that would result in the most balanced distribution
        best_group = 0
        min_max_difference = float('inf')
        
        for g in range(num_groups):
            # Calculate what the max difference would be if we add to this group
            temp_totals = group_totals.copy()
            temp_totals[g] += total_time
            max_diff = max(temp_totals) - min(temp_totals)
            
            if max_diff < min_max_difference:
                min_max_difference = max_diff
                best_group = g
        
        # Add to best group
        groups[best_group].append((comp, total_time))
        group_totals[best_group] += total_time
    
    return groups, group_totals

def split_competitions_balanced_multiple(b, c, num_groups=8, max_copies=3):
    """
    More balanced splitting allowing competitions to appear in multiple groups
    If a competition doesn't exist in the sample set, use the average of all existing items
    """
    # Calculate average execution time and scripts for missing competitions
    avg_exec_time = sum(b.values()) / len(b) if b else 0
    avg_scripts = sum(c.values()) / len(c) if c else 0
    
    # Calculate total times
    competitions = []
    for comp in b.keys():
        if comp in c:
            total_time = b[comp] * c[comp]
            competitions.append((comp, total_time))
        else:
            # Use average values for missing competition
            total_time = avg_exec_time * avg_scripts
            competitions.append((comp, total_time))
            c[comp] = int(avg_scripts)  # Add to c with average scripts
    
    # Also handle competitions in c but not in b
    for comp in c.keys():
        if comp not in b:
            b[comp] = avg_exec_time  # Add to b with average execution time
            total_time = b[comp] * c[comp]
            competitions.append((comp, total_time))
    
    # Sort by total time
    competitions.sort(key=lambda x: x[1], reverse=True)
    
    # Initialize groups
    groups = [[] for _ in range(num_groups)]
    group_totals = [0.0] * num_groups
    comp_usage_count = {}  # Track how many times each comp has been used
    comp_scripts_per_group = {}  # Track scripts per group for each competition
    
    # For better balance, allow competitions to be assigned to multiple groups
    for comp, total_time in competitions:
        # Initialize usage count for this competition
        if comp not in comp_usage_count:
            comp_usage_count[comp] = 0
            comp_scripts_per_group[comp] = {}
        
        # Determine how many copies of this competition to create
        # Larger competitions get more copies (up to max_copies)
        if total_time > sum([t for _, t in competitions]) / len(competitions) * 2:
            # Large competitions get more copies
            num_copies = min(max_copies, num_groups // 2)
        else:
            # Smaller competitions get fewer copies
            num_copies = min(2, max_copies)
        
        # Calculate scripts per group (distribute total scripts across groups)
        scripts_per_group = c[comp] // num_copies
        remaining_scripts = c[comp] % num_copies
        
        # Find the best groups for this competition
        group_scores = []
        for g in range(num_groups):
            # Calculate what the balance would be if we add to this group
            temp_totals = group_totals.copy()
            # Use scripts_per_group for time calculation
            group_time = b[comp] * scripts_per_group
            temp_totals[g] += group_time
            # Score based on how balanced this would make the distribution
            max_diff = max(temp_totals) - min(temp_totals)
            group_scores.append((g, max_diff, group_totals[g]))
        
        # Sort by balance score (lower is better), then by current load
        group_scores.sort(key=lambda x: (x[1], x[2]))
        
        # Assign to the best num_copies groups
        assigned_count = 0
        for g, _, current_load in group_scores:
            if assigned_count >= num_copies:
                break
            
            # Determine scripts for this group
            group_scripts = scripts_per_group
            if assigned_count < remaining_scripts:  # Distribute remaining scripts
                group_scripts += 1
            
            # Calculate time for this group
            group_time = b[comp] * group_scripts
            
            # Add to this group
            groups[g].append((comp, group_time))
            group_totals[g] += group_time
            comp_usage_count[comp] += 1
            comp_scripts_per_group[comp][g] = group_scripts
            assigned_count += 1
    
    return groups, group_totals, comp_usage_count, comp_scripts_per_group


def process_gpu_files_separate(gpu_id, parrallel_groups, setting):  
    # print(f"GPU {gpu_id}: Processing {len(parrallel_groups)} files")

    timeout_seconds = 600
    # Create output directory if it doesn't exist
    output_dir = "/home/b27jin/mle-bench-internal/docker-test/output"
    os.makedirs(output_dir, exist_ok=True)

    with open('/home/b27jin/config.json', 'r', encoding='utf-8') as file:
        config = json.load(file)
    k_token = config['kaggle']

    expected = "/home/b27jin/mle-bench-internal/docker-test/scripts" if setting == "test" else "/home/b27jin/mle-bench-internal/docker-test/scripts_full"
    nb_out = Path('./scripts_out')
    results = {}

    # Use separate JSON file for each GPU
    json_filename = f'executable_files_w_timer_gpu_{gpu_id}.json' if setting == "test" else f'executable_files_w_timer_gpu_{gpu_id}_full.json'

    if setting == "test":
        all_files = [f for f in os.listdir(expected) if f.endswith('.ipynb')]
        parrallel_groups = [f for f in all_files if f.split("_")[0] in parrallel_groups]

    # for filename in tqdm(os.listdir(expected)):
    for filename in tqdm(parrallel_groups, desc=f"GPU {gpu_id}",
                        position=gpu_id,  # Each GPU gets its own line
                        leave=True):      # Keep bar visible after completion
        # print(f"\r\n{filename}", end='', flush=True)
        p_time_start = time.time()

        parts = filename.split("_")
        compt = parts[0]
        notebook_name = "_".join(parts[1:-2])
        version = parts[-2]
        out_path = nb_out / compt / notebook_name / version

        # Clear all outputs from the notebook file before processing
        notebook_path = os.path.join(expected, filename)
        if not clear_notebook_outputs(notebook_path):
            print(f"Failed to clear outputs from {filename}")
        
        # Create temporary working directory
        temp_dir = tempfile.mkdtemp(prefix=f'gpu_{gpu_id}_')
        shutil.copy2(os.path.join(expected, filename), temp_dir)

        subprocess.run([f'chmod -R a+rw {temp_dir}'], shell=True, check=True)

        # Snapshot before run (existing files)
        before = set(Path(temp_dir).glob("*.csv"))


        upperdir = tempfile.mkdtemp(prefix=f'overlay_upper_{gpu_id}_')
        workdir = tempfile.mkdtemp(prefix=f'overlay_work_{gpu_id}_')
        dst = f'/home/b27jin/mle-bench-internal/tester/{filename.split(".")[0]}'
        os.makedirs(dst, exist_ok=True)


        try:
            # sudo mount -t overlay overlay  -o lowerdir="/home/b27jin/mle-bench-internal/docker-test/test",upperdir="/tmp/overlay-upper",workdir="/tmp/overlay-work" .
            subprocess.run([f'sudo mount -t overlay overlay -o lowerdir="/home/b27jin/.cache/mle-bench/data/{compt}",upperdir="{upperdir}",workdir="{workdir}" "{dst}"'], shell=True, check=True)

            # cleanup_cmd = f'docker ps -aq --filter "name=gpu_{gpu_id}_*" | xargs -r docker rm -f'
            # subprocess.run([cleanup_cmd], shell=True, 
            #             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            while not (os.path.exists(f"{dst}/prepared/public") and os.path.isdir(f"{dst}/prepared/public")):  # Ensure mount is ready
                time.sleep(0.1)
                
            cmd,container_name = build_docker_command(k_token, temp_dir, compt, filename, gpu_id, dst)
            
            # Run notebooks with timeout monitoring
            runner = NotebookRunner(timeout_seconds)
            result = runner.run_single_notebook(cmd, compt, filename)
            results[filename] = result

            # Move the nb file (w/ outputs) to expected directory
            temp_notebook_path = os.path.join(temp_dir, filename)

            # save nb back to new dir e.g., ./scripts_out
            if not os.path.exists(out_path):
                os.makedirs(out_path, exist_ok=True)

            if os.path.exists(temp_notebook_path):
                shutil.copy(temp_notebook_path, out_path)
                shutil.copy(temp_notebook_path, './scripts_out_all')

            # Snapshot after run (detect new .csv files)
            after = set(Path(temp_dir).glob("*.csv"))
            
            # save nb back to new dir e.g., scripts_out/
            # scripts_out/{compt}/{username}/{version}/ (1) csv (2) notebook (3) json
            new_csvs = after - before
            # Move and rename new CSV files
            for csv_path in new_csvs:
                new_name = filename.rsplit(".", maxsplit=1)[0] + ".csv"
                destination = os.path.join(out_path, new_name)
                shutil.copy(str(csv_path), os.path.join(output_dir, new_name))
                shutil.move(str(csv_path), str(destination))
                results[filename]["output"] = f"{destination}"
                results[filename]['status'] = 'csv_created'

        except Exception as e:
            results[filename]['error'] = str(traceback.format_exc())

        # Cleanup temp dir
        start = time.time()

        subprocess.run([f'sudo umount {dst}'], shell=True, check=True)
        subprocess.run([f'sudo rm -rf {temp_dir}'], shell=True, check=True)
        subprocess.run([f'sudo rm -rf {upperdir}'], shell=True, check=True)
        subprocess.run([f'sudo rm -rf {workdir}'], shell=True, check=True)

        try:
            subprocess.run([f'rm -rf {dst}'], shell=True, check=True)
        except Exception as e:
            subprocess.run([f'sudo umount -f {dst} 2>/dev/null || true'], shell=True)
            subprocess.run([f'rm -rf {dst}'], shell=True)

        end = time.time()
        results[filename]['cleanup_time'] = end - start


        subprocess.run([f'docker kill {container_name}'], shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT)
    

        p_time_end = time.time()
        results[filename]['process_time'] = p_time_end - p_time_start

        with open(out_path / 'result.json', 'w', encoding='utf-8') as f:
            json.dump(results[filename], f, indent=2, ensure_ascii=False)

        with open(json_filename, 'w', encoding='utf-8') as file:
            fcntl.flock(file.fileno(), fcntl.LOCK_EX)
            json.dump(results, file, indent=2, ensure_ascii=False)
            fcntl.flock(file.fileno(), fcntl.LOCK_UN)

import multiprocessing as mp
import sys
if __name__ == "__main__":
    setting = sys.argv[1]
    if not setting:
        sys.exit(1)

    if not os.path.exists('./scripts_out_all'):
        os.makedirs('./scripts_out_all', exist_ok=True)
    if not os.path.exists('./scripts_out'):
        os.makedirs('./scripts_out', exist_ok=True)
    if not os.path.exists('./scripts'):
        os.makedirs('./scripts', exist_ok=True)
    if not os.path.exists('./output'):
        os.makedirs('./output', exist_ok=True)


    compt = []

    with open('executable_files_w_timer_parrallel.json', 'r') as f:
        data = json.load(f)
    for entity, info in data.items():
        compt.append(entity.split("_")[0])

    a = list(set(compt))

    b = {value: [] for value in a}

    for entity, info in data.items():
        if "process_time" in info:
            b[entity.split("_")[0]].append(info["process_time"])

    for key, val in b.items():
        b[key] = sum(val) / len(val) if val else 0


    c = {value: 0 for value in a}
    full_files = [f for f in os.listdir("./scripts_full") if f.endswith('.ipynb')]
    expected = './scripts'
    # Remove sample scripts
    sample_files = [f for f in os.listdir(expected) if f.endswith('.ipynb')]
    sample_files = [x for x in full_files if x not in sample_files]

    print(len(sample_files), setting)
    for entity in sample_files:
        if entity.split("_")[0] in c:
            c[entity.split("_")[0]] += 1
        else:
            c[entity.split("_")[0]] = 1

    if setting == "test":
        del b['spaceship-titanic']
        del c['spaceship-titanic']

        # Use the function
        groups, group_totals = split_competitions_balanced(b, c, 7)

        parrallel_groups = {0: ["spaceship-titanic"]}

        # Display results
        for i, (group, total) in enumerate(zip(groups, group_totals)):
            parrallel_groups[i+1] = [comp for comp, time in group]
    else:
        # Use the function with multi-group assignment
        groups, group_totals, comp_usage, comp_scripts_per_group = split_competitions_balanced_multiple(b, c, 8, max_copies=8)

        parrallel_groups = {}
        remaining_files = sample_files.copy()  # Work with a copy to avoid modifying original

        for group_id in range(len(groups)):
            parrallel_groups[group_id] = []
            
            # Get competitions in this group and their required script counts
            for comp, _ in groups[group_id]:
                required_scripts = comp_scripts_per_group[comp].get(group_id, 0)
                
                # Find files for this competition that haven't been assigned yet
                comp_files = [f for f in remaining_files if f.split("_")[0] == comp]
                
                # Assign up to required_scripts files for this competition
                assigned_count = 0
                files_to_remove = []
                
                for file in comp_files:
                    if assigned_count >= required_scripts:
                        break
                    parrallel_groups[group_id].append(file)
                    files_to_remove.append(file)
                    assigned_count += 1
                
                # Remove assigned files from remaining_files
                for file in files_to_remove:
                    remaining_files.remove(file)
                
                # If we couldn't assign enough files, print a warning
                if assigned_count < required_scripts:
                    print(f"Warning: Group {group_id}, competition {comp} - only assigned {assigned_count} files out of {required_scripts} required")



    # for group_id in range(len(parrallel_groups)):
    #     print(f"Group {group_id}: {len(parrallel_groups[group_id])}")
    # # Create processes for each GPU
    processes = []
    for gpu_id in range(8):  # GPUs 0-7
        p = mp.Process(
            target=process_gpu_files_separate,
        args=(gpu_id, parrallel_groups[gpu_id], setting)
        )
        processes.append(p)
        p.start()

    for i, p in enumerate(processes):
        p.join()  # This still waits, but now you see all started first
        print(f"GPU {i} process completed")

    subprocess.run([f'docker kill $(docker ps -q)'], shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT)

    time.sleep(2)
    # Merge all GPU results into final file
    merge_gpu_results(setting)
    

    # # sudo pkill -f tmux
    # # pkill -u b27jin 
    # # sudo umount -f /home/b27jin/mle-bench-internal/tester/* 2>/dev/null || true
    # # rm -rf /home/b27jin/mle-bench-internal/tester/*
    # # conda activate mle_env && cd mle-bench-internal/docker-test/ && time taskset -c 0-7 python3.11 run_docker_w_timer_parrallel.py test/full
    # # conda activate mle_env && cd mle-bench-internal/docker-test/ && time taskset -c 0-1 python run_docker_w_timer_parrallel.py 0
    # # conda activate mle_env && cd mle-bench-internal/docker-test/ && time taskset -c 2-3 python run_docker_w_timer_parrallel.py 1
    # # conda activate mle_env && cd mle-bench-internal/docker-test/ && time taskset -c 4-5 python run_docker_w_timer_parrallel.py 2
    # # conda activate mle_env && cd mle-bench-internal/docker-test/ && time taskset -c 6-7 python run_docker_w_timer_parrallel.py 3
    # # conda activate mle_env && cd mle-bench-internal/docker-test/ && time taskset -c 8-9 python run_docker_w_timer_parrallel.py 4
    # # conda activate mle_env && cd mle-bench-internal/docker-test/ && time taskset -c 10-11 python run_docker_w_timer_parrallel.py 5
    # # conda activate mle_env && cd mle-bench-internal/docker-test/ && time taskset -c 12-13 python run_docker_w_timer_parrallel.py 6
    # # conda activate mle_env && cd mle-bench-internal/docker-test/ && time taskset -c 14-15 python run_docker_w_timer_parrallel.py 7
    # gpu_id = int(sys.argv[1])
    # gpu_id = 0
    # # print(sys.argv)
    # process_gpu_files_separate(gpu_id,parrallel_groups[gpu_id])


    # # Create processes for each GPU
    # processes = []
    # for gpu_id in range(8):  # GPUs 0-7
    #     p = mp.Process(
    #         target=process_gpu_files_separate,
    #         args=(gpu_id, parrallel_groups[gpu_id])
    #     )
    #     processes.append(p)
    #     p.start()
    
    # for i, p in enumerate(processes):
    #     p.join()  # This still waits, but now you see all started first
    #     print(f"GPU {i} process completed")



    # max_workers = 8  # Number of threads (matching your 8 GPUs)
    # # Using ThreadPoolExecutor instead of multiprocessing
    # with ThreadPoolExecutor(max_workers=max_workers) as executor:
    #     # Submit all GPU tasks to the thread pool
    #     future_to_gpu = {
    #         executor.submit(process_gpu_files_separate, gpu_id, parrallel_groups[gpu_id]): gpu_id 
    #         for gpu_id in range(8)
    #     }

    #     # Monitor completion
    #     for future in as_completed(future_to_gpu):
    #         gpu_id = future_to_gpu[future]
    #         result = future.result()


    # # Create threads for each GPU
    # threads = []
    # for gpu_id in range(8):
    #     t = threading.Thread(
    #         target=process_gpu_files_separate,
    #         args=(gpu_id, parrallel_groups[gpu_id])
    #     )
    #     threads.append(t)
    #     t.start()
    #     print(f"Started thread for GPU {gpu_id}")
    
    # # Wait for all threads to complete
    # for i, t in enumerate(threads):
    #     t.join()
    #     print(f"GPU {i} process completed")
