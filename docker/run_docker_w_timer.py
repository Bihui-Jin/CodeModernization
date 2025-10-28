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

class NotebookRunner:
    def __init__(self, timeout_seconds):
        self.timeout_seconds = timeout_seconds
        
    def monitor_execution(self, process, timeout_event, start_event, execution_queue):
        """Monitor Docker process output and detect execution start"""
        execution_started = False
        start_time = None

        try:
            while process.poll() is None and not timeout_event.is_set():
                # Use select to check if there's output available without blocking indefinitely
                ready, _, _ = select.select([process.stdout], [], [], 0.1)

                
                if ready:
                    # Reads stdout line-by-line from the subprocess
                    line = process.stdout.readline()
                    if line:
                        line = line.strip().replace('\r', '').replace('\x1b[K', '')
                        execution_queue.put(('output', line))
                        
                        # Detect when notebook execution starts (usually the message starts with '[NbClientApp] Executing notebook with kernel:')
                        if not execution_started and any(keyword in line.lower() for keyword in [
                            'executing notebook', 'executing cell', 'executing:', 'running cell', "debugging will proceed"
                        ]):
                            execution_started = True
                            start_time = time.time()
                            start_event.set()
                            execution_queue.put(('status', 'Execution started'))
                    
                # Check timeout only after execution has started
                if execution_started and start_time:
                    elapsed_time = time.time() - start_time

                    # Use carriage return to overwrite the same line
                    print(f"\rElapsed time: {elapsed_time:.1f}s", end='', flush=True)

                    if elapsed_time > self.timeout_seconds:
                        print(f"\nTimeout after {elapsed_time:.1f}s")
                        execution_queue.put(('status', f'Timeout after {elapsed_time:.1f}s'))
                        timeout_event.set()
                        break
               
                # time.sleep(0.1)
                
        except Exception as e:
            execution_queue.put(('error', str(e)))
    
    def run_single_notebook(self, docker_command):
        """Run a single notebook with timeout monitoring"""

        # Start a subprocess
        process = subprocess.Popen(
            docker_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
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
            args=(process, timeout_event, start_event, execution_queue)
        )
        monitor_thread.daemon = True
        monitor_thread.start()
        
        execution_time = 0
        result = {
            # 'success': False,
            # 'execution_time': 0,
            # 'timeout': False,
            # 'error': None
        }
        
        try:
            start_time = None
            
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
            
            # result['success'] = process.returncode == 0

            remaining_output = process.stdout.read() if process.stdout else process.stderr.read() if process.stderr else ""
            if remaining_output:
                result['detail'] = re.sub(r'\x1b\[[0-9;]*m', '', remaining_output).encode('utf-8').decode('unicode_escape') 
            
        except KeyboardInterrupt:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            result['error'] = 'Interrupted by user'
        except Exception as e:
            result['error'] = str(e)
        
        return result
    

def build_docker_command(k_token, temp_dir, compt, filename):
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
        f"/home/b27jin/.cache/mle-bench/data/{compt}/prepared/public/train": "/kaggle/input/train/train",
        f"/home/b27jin/.cache/mle-bench/data/{compt}/prepared/public/train2": "/kaggle/input/train/train2",
        f"/home/b27jin/.cache/mle-bench/data/{compt}/prepared/public/train_images": "/kaggle/input/train/train",
        f"/home/b27jin/.cache/mle-bench/data/{compt}/prepared/public/train_images": "/kaggle/input/train/train_images",
        f"/home/b27jin/.cache/mle-bench/data/{compt}/prepared/public/train_images": "/kaggle/input/train_images/train_images",
        f"/home/b27jin/.cache/mle-bench/data/{compt}/prepared/public/test": "/kaggle/input/test/test",
        f"/home/b27jin/.cache/mle-bench/data/{compt}/prepared/public/test_images": "/kaggle/input/test/test",
        f"/home/b27jin/.cache/mle-bench/data/{compt}/prepared/public/test_images": "/kaggle/input/test/test_images",
        f"/home/b27jin/.cache/mle-bench/data/{compt}/prepared/public/test_images": "/kaggle/input/test_images/test_images",
        f"/home/b27jin/.cache/mle-bench/data/{compt}/prepared/public/test2": "/kaggle/input/test/test2"
    }

    volume_mounts =[]

    # Add only existing directories
    for host_path, container_path in optional_paths.items():
        if os.path.exists(host_path) and os.path.isdir(host_path):
            volume_mounts.append(f'"{host_path}:{container_path}"')

    cmd = 'docker run --rm -it --shm-size=30g --cpuset-cpus="6,7,8,9" --gpus all'
    cmd += " -e CUDA_VISIBLE_DEVICES=5"
    cmd += f' -e KAGGLE_USER_SECRETS_TOKEN="{k_token}"'
    cmd += f' -v {temp_dir}:/kaggle/working'
    cmd += f' -v /home/b27jin/.cache/mle-bench/data/{compt}/prepared/public:/kaggle/input'
    cmd += f" -v /home/b27jin/.cache/mle-bench/data/{compt}/prepared/public:/kaggle/input/{compt}"
    # cmd += f' -v /home/b27jin/.cache/mle-bench/data/{compt}/prepared/public:/kaggle/working'
    cmd += f' -v /home/b27jin/.cache/mle-bench/data/{compt}/prepared/public:/kaggle/working/{compt}'
    cmd += f' -v /home/b27jin/.cache/mle-bench/data/{compt}/prepared/public:/kaggle/data'
    cmd += f' -v /home/b27jin/.cache/mle-bench/data/{compt}/prepared/public:/kaggle/data/{compt}'
    cmd += "".join([f" -v {mount}" for mount in volume_mounts])
    cmd += " -w /kaggle/working kaggle_mle"
    cmd += f" jupyter nbconvert --to notebook --inplace --execute {filename} --ExecutePreprocessor.allow_errors=True --ExecutePreprocessor.timeout=-1"
    
    return cmd

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
        
        # # Save the cleared notebook
        # with open(notebook_path, 'w', encoding='utf-8') as f:
        #     json.dump(notebook, f, indent=2, ensure_ascii=False)



        # with open(notebook_path, 'r', encoding='utf-8') as f:
        #     notebook = json.load(f)

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
    
# Example usage
if __name__ == "__main__":
    timeout_seconds = 600 * 1.2
    # Create output directory if it doesn't exist
    output_dir = "/home/b27jin/mle-bench-internal/docker-test/output"
    os.makedirs(output_dir, exist_ok=True)

    with open('/home/b27jin/config.json', 'r', encoding='utf-8') as file:
        config = json.load(file)
    k_token = config['kaggle']
    
    # try:
    #     with open('executable_files_w_timer.json', 'r', encoding='utf-8') as file:
    #         results = json.load(file)
    #     timeout_files = [
    #         fn
    #         for fn, meta in results.items()
    #         if meta.get('execution_time', 0) >= timeout_seconds
    #     ]
    # except FileNotFoundError:
    #     results = {}
    results = {}
    expected = "./scripts"
    for filename in tqdm(os.listdir(expected)):
    # for filename in tqdm(timeout_files):
        # if filename == "dog-breed-identification_hongpeiyi_identify-dog-breed-using-single-resnet-with-fastai_v31_C1.ipynb":
        # if filename == "dogs-vs-cats-redux-kernels-edition_alfamame_pytorch-imagefolder-resnet50_v4_C1.ipynb":
        # if filename == "spaceship-titanic_hirakuhasegawa_lightgbm-spaceship-titanic_v8_C1.ipynb":
        # if filename == "tweet-sentiment-extraction_tonyjchen_group8_v17_C1.ipynb":
        # if filename in ["tweet-sentiment-extraction_gangakrish_keyword-extraction-from-tweets_v27_C1.ipynb",
        # "tweet-sentiment-extraction_garbamoussa_tweet-sentiment-extraction-0-594_v35_C1.ipynb",
        # "spaceship-titanic_viktortaran_space-titanic_v91_C1.ipynb"]:
            print(f"\r\n{filename}", end='', flush=True)
            compt = filename.split("_")[0]

            # Clear all outputs from the notebook file before processing
            notebook_path = os.path.join(expected, filename)
            if not clear_notebook_outputs(notebook_path):
                print(f"Failed to clear outputs from {filename}")
            
            # Create temporary working directory
            temp_dir = tempfile.mkdtemp()
            shutil.copy2(os.path.join(expected, filename), temp_dir)

            subprocess.run([f'chmod -R a+rw {temp_dir}'], shell=True, check=True)

            # Snapshot before run (existing files)
            before = set(Path(temp_dir).glob("*.csv"))

            cmd = build_docker_command(k_token, temp_dir, compt, filename)

            # Run notebooks with timeout monitoring
            runner = NotebookRunner(timeout_seconds)
            result = runner.run_single_notebook(cmd)

            results[filename] = result

            # Move the nb file (w/ outputs) to expected directory
            temp_notebook_path = os.path.join(temp_dir, filename)
            if os.path.exists(temp_notebook_path):
                shutil.copy(temp_notebook_path, expected)
        
            # Snapshot after run (detect new .csv files)
            after = set(Path(temp_dir).glob("*.csv"))
            
            new_csvs = after - before
            # Move and rename new CSV files
            for csv_path in new_csvs:
                new_name = filename.split(".")[0] + ".csv"
                destination = os.path.join(output_dir, new_name)
                shutil.move(str(csv_path), str(destination))
                results[filename]["output"] = f"{destination}"
                results[filename]['status'] = 'csv_created'

            # Cleanup temp dir
            if os.path.exists(temp_dir):
                subprocess.run([f'sudo rm -rf {temp_dir}'], shell=True, check=True)
            
            start = time.time()
            subprocess.run([f'sudo chmod -R a+rw /home/b27jin/.cache/mle-bench/data/{compt}'], shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT)
            subprocess.run([f"cd /home/b27jin/.cache/mle-bench/data/{compt} && git checkout -f . && git clean -fddx"], shell=True, check=True)
            subprocess.run([f'chmod -R a+rw /home/b27jin/.cache/mle-bench/data/{compt}'], shell=True, check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT)

            subprocess.run([f'docker kill $(docker ps -q)'], shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT)
            end = time.time()

            results[filename]['git_time'] = end - start

            with open('executable_files_w_timer.json', 'w', encoding='utf-8') as file:
                json.dump(results, file, indent=2, ensure_ascii=False)
            

    # Print summary
    print("\n" + "="*60)
    print("EXECUTION SUMMARY")
    print("="*60)
    
    timeouts = 0
    failures = 0
    csv_created = 0

    for filename, result in results.items():
        status = result.get('status', 'unknown')
        if status == 'csv_created':
            exec_time = result.get('execution_time', 0)
            csv_created += 1
        elif status == 'timeout':
            timeouts += 1
        else:
            error_msg = result.get('error', 'Unknown error')
            failures += 1
    
    print("-"*60)
    print(f"Total: {len(results)} | CSV Created: {csv_created} | Timeout: {timeouts} | Failed: {failures}")