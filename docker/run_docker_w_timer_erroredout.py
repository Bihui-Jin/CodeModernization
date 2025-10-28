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
                    print(f"\rElapsed {compt} time: {elapsed_time:.1f}s", end='', flush=True)

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
    cmd += f' --cpuset-cpus="8,9,10,11"'
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



def process_gpu_files_separate(gpu_id, parrallel_groups):  
    # print(f"GPU {gpu_id}: Processing {len(parrallel_groups)} files")

    timeout_seconds = 600
    # Create output directory if it doesn't exist
    output_dir = "/home/b27jin/mle-bench-internal/docker-test/output"
    os.makedirs(output_dir, exist_ok=True)

    with open('/home/b27jin/config.json', 'r', encoding='utf-8') as file:
        config = json.load(file)
    k_token = config['kaggle']

    expected = "/home/b27jin/mle-bench-internal/docker-test/scripts_full"
    nb_out = Path('./scripts_out')
    results = {}

    # Use separate JSON file for each GPU
    json_filename = f'executable_files_w_timer_timeout.json'

    # for filename in tqdm(os.listdir(expected)):
    for filename in tqdm(parrallel_groups):
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

        cmd,container_name = build_docker_command(k_token, temp_dir, compt, filename, gpu_id, dst)

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

    files = []
    with open('executable_files_w_timer_parrallel_full.json', 'r') as f:
        data = json.load(f)
    print(len(data), "files to process")

    for file, values in data.items():
        if "timeout" in values or values.get('execution_time', 0) > 600:
            files.append(file)
    print(len(files), "files were timed out")

    process_gpu_files_separate(0, files)

    subprocess.run([f'docker kill $(docker ps -q)'], shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT)

    time.sleep(1)


    timeout_file = 'executable_files_w_timer_timeout.json'
    main_file = 'executable_files_w_timer_parrallel_full.json'
    
    try:
        # Load both files
        with open(timeout_file, 'r', encoding='utf-8') as f:
            timeout_data = json.load(f)
        
        with open(main_file, 'r', encoding='utf-8') as f:
            main_data = json.load(f)
        
        print(f"Processing {len(timeout_data)} timeout entries...")
        
        for filename, new_result in timeout_data.items():
            # CLEAN: Remove old timeout-related data
            if not new_result.get('timeout'):
                main_data[filename] = new_result.copy()

        
        # Save updated main file with sorted keys
        with open(main_file, 'w', encoding='utf-8') as f:
            json.dump(dict(sorted(main_data.items())), f, indent=2, ensure_ascii=False)
        
        
    except FileNotFoundError as e:
        print(f"File not found: {e}")
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {e}")
    except Exception as e:
        print(f"Error updating main results: {e}")
