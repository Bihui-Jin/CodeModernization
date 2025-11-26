import json
import os

# Paths
JSON_PATH = "apiDowngrade/kernel_w_pyVersion.json"
REQ_DIR = "apiDowngrade/apiDowngradeList"
DOCKERFILE_PATH = "apiDowngrade/Dockerfile.base"

# Header of the Dockerfile
dockerfile_content = """FROM ubuntu:20.04

# Avoid interactive dialog
ENV DEBIAN_FRONTEND=noninteractive

# 1. Install system dependencies and build tools
RUN apt-get update && apt-get install -y \\
    apt-utils curl wget git vim nano unzip zip p7zip-full \\
    build-essential libssl-dev zlib1g-dev \\
    libbz2-dev libreadline-dev libsqlite3-dev llvm \\
    libncurses5-dev libncursesw5-dev xz-utils tk-dev \\
    libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev \\
    python-openssl \\
    sudo openssh-server tmux gettext ffmpeg libsm6 libxext6 \\
    && rm -rf /var/lib/apt/lists/* # removes cache

RUN apt-get update && apt-get install -y --no-install-recommends \\
    apt-utils ca-certificates gnupg \\
    && rm -rf /var/lib/apt/lists/*

# 2. Install NVIDIA container toolkit
RUN curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg \\
  && curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \\
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \\
    sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

RUN sudo apt-get update

RUN export NVIDIA_CONTAINER_TOOLKIT_VERSION=1.17.8-1 \\
  && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \\
      nvidia-container-toolkit=${NVIDIA_CONTAINER_TOOLKIT_VERSION} \\
      nvidia-container-toolkit-base=${NVIDIA_CONTAINER_TOOLKIT_VERSION} \\
      libnvidia-container-tools=${NVIDIA_CONTAINER_TOOLKIT_VERSION} \\
      libnvidia-container1=${NVIDIA_CONTAINER_TOOLKIT_VERSION}

RUN sudo nvidia-ctk runtime configure --runtime=docker

# 3. Install pyenv to manage multiple Python versions
ENV PYENV_ROOT="/opt/pyenv"
ENV PATH="$PYENV_ROOT/bin:$PYENV_ROOT/shims:$PATH"
RUN curl -fsSL https://pyenv.run | bash

# 4. Copy requirement files into the image
COPY apiDowngrade/apiDowngradeList /tmp/requirements/

# 5. Pre-install necessary Python versions using pyenv
# We collect all unique versions first to minimize build layers
"""

def generate():
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        kernel_content = json.load(f)

    # Collect valid tasks and unique python versions
    tasks = []
    unique_versions = set()

    for compt, files in kernel_content.items():
        for fname, script_meta in files.items():
            # Filter conditions
            if "ps" in script_meta and script_meta['runtime'] <= 600 and len(script_meta['datasets'])<=1 and "R" not in script_meta:
                
                py_ver = script_meta.get("python")
                if not py_ver:
                    print(f"!!!Skipping {compt}_{fname} due to missing python version!!!")
                    continue
                
                # Clean filename for env name
                clean_fname = fname.split(".")[0]
                env_name = f"{compt}_{clean_fname}"
                
                tasks.append({
                    "env_name": env_name,
                    "python_version": py_ver,
                })
                unique_versions.add(py_ver)

    # Add commands to install Python versions
    dockerfile_content_local = dockerfile_content
    dockerfile_content_local += "# Installing Python versions (this takes time)\n"
    
    # Sort versions to keep build deterministic
    for ver in sorted(unique_versions):
        dockerfile_content_local += f"RUN eval \"$(pyenv init -)\" && pyenv install {ver} && pyenv global {ver} && pip install --upgrade pip virtualenv\n"

    dockerfile_content_local += "\n# Creating Virtual Environments and Installing Requirements\n"
    dockerfile_content_local += "WORKDIR /opt/venvs\n\n"

    # Add commands to create venvs and install requirements
    # We group them to reduce layers, or keep separate for caching. 
    # Grouping is better for image size, separate is better for debugging.
    # Here we group by Python version to optimize switching.
    
    for task in tasks:
        env = task['env_name']
        ver = task['python_version']
        req_path = f"/tmp/requirements/{env}.txt" 
        
        # Command:
        # 1. Switch to specific python version
        # 2. Create venv
        # 3. Activate and install requirements
        cmd = f"""RUN pyenv local {ver} && \\
    virtualenv {env} && \\
    . {env}/bin/activate && \\
    pip install --upgrade pip && \\
    pip install -r /tmp/requirements/{env}.txt

""" if ver.startswith("3.") else f"""RUN pyenv local {ver} && \\
    virtualenv {env} && \\
    . {env}/bin/activate && \\
    pip install -r /tmp/requirements/{env}.txt

"""
        dockerfile_content_local += cmd

    # Final cleanup
    dockerfile_content_local += "\n# Cleanup\nRUN rm -rf /tmp/requirements\n"
    dockerfile_content_local += "# Reset DEBIAN_FRONTEND\nENV DEBIAN_FRONTEND=\n"

    with open(DOCKERFILE_PATH, "w", encoding="utf-8") as f:
        f.write(dockerfile_content_local)
    
    print(f"Dockerfile generated at {DOCKERFILE_PATH} with {len(tasks)} environments.")

if __name__ == "__main__":
    generate()