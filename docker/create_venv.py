import json
import os
import re
from packaging import version

# Paths
BASE_IMAGE = "gcr.io/kaggle-gpu-images/python"
JSON_PATH = "apiDowngrade/kernel_w_pyVersion.json"
REQ_DIR = "apiDowngrade/apiDowngradeList"
NLTK_CORPORA_FILE = "baseline/nltk_corpora.txt"
DOCKERFILE_PATH = "docker/Dockerfile.base"
REQUIREMENTS_PATH = "baseline/requirements.txt"

def parse_version(v):
    # Returns (major, minor, patch_int, original_patch_str)
    parts = v.split(".")
    if len(parts) < 2:
        return None
    major = int(parts[0])
    minor = int(parts[1])
    patch = 0
    patch_str = "0"
    if len(parts) > 2:
        m = re.match(r"(\d+)", parts[2])
        if m:
            patch = int(m.group(1))
            patch_str = m.group(1)
    return (major, minor, patch, patch_str)

def load_kernel():
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def collect_tasks(kernel):
    tasks = []
    versions_used = set()
    for compt, files in kernel.items():
        for fname, meta in files.items():
            if ("ps" in meta and
                meta.get('runtime', float('inf')) <= 600 and
                len(meta.get('datasets', [])) <= 1 and
                "R" not in meta):
                py_ver = meta.get("python")
                if not py_ver:
                    print(f"!!!Skipping {compt}_{fname} due to missing python version!!!")
                    continue
                env_name = f"{compt}_{fname.split('.')[0]}"
                tasks.append((env_name, py_ver))
                versions_used.add(py_ver)
    return tasks, versions_used

def consolidate_versions(versions):
    # # Keep only highest patch per (major, minor)
    # groups = {}
    # for v in versions:
    #     pv = parse_version(v)
    #     if not pv:
    #         continue
    #     major, minor, patch, _ = pv
    #     key = (major, minor)
    #     if key not in groups or patch > groups[key][2]:
    #         groups[key] = pv  # store full tuple
    # # Rebuild consolidated version strings
    # consolidated = {}
    # for (major, minor), (_M, _m, patch, patch_str) in groups.items():
    #     consolidated[(major, minor)] = f"{major}.{minor}.{patch_str}"

    # Keep only major.minor versions
    consolidated = set()
    for v in versions:
        pv = parse_version(v)
        if not pv:
            continue
        major, minor, patch, _ = pv
        consolidated.add(f"{major}.{minor}")
    return consolidated

def map_task_versions(tasks, consolidated_map=None):
    # mapped = []
    # for env_name, original_v in tasks:
    #     pv = parse_version(original_v)
    #     if not pv:
    #         continue
    #     major, minor = pv[0], pv[1]
    #     chosen = consolidated_map.get((major, minor))
    #     if not chosen:
    #         continue
    #     mapped.append((env_name, chosen))

    # Keep only first encountered version per (major, minor)
    mapped = []
    for env_name, original_v in tasks:
        pv = parse_version(original_v)
        if not pv:
            continue
        major, minor = pv[0], pv[1]
        # Keep only first encountered version per (major, minor), e.g., 3.5
        chosen = f"{major}.{minor}"
        mapped.append((env_name, chosen))
    return mapped

def read_nltk_corpora():
    with open(NLTK_CORPORA_FILE, "r", encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip() and not l.startswith("#")]

# Header of the Dockerfile
dockerfile_content = f"""# docker pull gcr.io/kaggle-images/python:latest (CPU-only) or gcr.io/kaggle-gpu-images/python:latest (GPU)
# Then build as follows:
# DOCKER_BUILDKIT=0 docker build --platform=linux/amd64 -t kaggle_code_envs -f docker/Dockerfile.base .
FROM {BASE_IMAGE}

# Avoid interactive dialog
ENV DEBIAN_FRONTEND=noninteractive

# 1. Install system dependencies and build tools
RUN apt-get update && apt-get install -y --no-install-recommends \\
    apt-utils ca-certificates gnupg \\
    curl wget git vim nano unzip zip p7zip-full \\
    build-essential libssl-dev zlib1g-dev \\
    libbz2-dev libreadline-dev libsqlite3-dev llvm \\
    libncurses5-dev libncursesw5-dev xz-utils tk-dev \\
    libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev \\
    # python-openssl \\
    sudo openssh-server tmux gettext ffmpeg libsm6 libxext6 \\
    && rm -rf /var/lib/apt/lists/* # removes cache

# 2. Install basic APIs that kaggle images do not include
ARG REQUIREMENTS=/tmp/requirements.txt
COPY {REQUIREMENTS_PATH} """+ """${REQUIREMENTS}
RUN pip install --upgrade pip setuptools wheel && \\
    python -m pip install --upgrade pip && \\
    # grep -v '^#' requirements.txt | xargs -n 1 pip install #--prefer-binary 
    pip install -r ${REQUIREMENTS} --prefer-binary 
    #--no-deps --ignore-installed  

# 3. Install NVIDIA container toolkit
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

# 4. Install pyenv to manage multiple Python versions
ENV PYENV_ROOT="/opt/pyenv"
ENV PATH="$PYENV_ROOT/bin:$PYENV_ROOT/shims:$PATH"
RUN curl -fsSL https://pyenv.run | bash

"""

def generate_dockerfile():
    kernel = load_kernel()
    tasks, versions_used = collect_tasks(kernel)
    consolidated_versions = consolidate_versions(versions_used)
    # mapped_tasks = map_task_versions(tasks, consolidated_map)
    mapped_tasks = map_task_versions(tasks)
    nltk_corpora = read_nltk_corpora()


    # Add commands to install Python versions
    dockerfile_content_local = dockerfile_content

    # Preload nltk corpora if any
    dockerfile_content_local += f"""# 5. Preload NLTK corpora
RUN python - <<EOF
import ssl, nltk

# allow unverified HTTPS context (for corporate proxies or missing certs)
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

# non-interactive, quiet downloads
for pkg in [{', '.join(repr(c) for c in nltk_corpora)}]:
    nltk.download(pkg, quiet=True)
    
EOF

"""

    dockerfile_content_local += f"""# 6. Copy requirement files into the image
COPY {REQ_DIR} /tmp/requirements/

# 7. Pre-install necessary Python versions using pyenv
# We collect all unique versions first to minimize build layers
"""
    
    # Sort versions to keep build deterministic
    for py_ver in sorted(consolidated_versions, key=lambda v: version.parse(v)):
        dockerfile_content_local += f"RUN eval \"$(pyenv init -)\" && pyenv install {py_ver} && pyenv global {py_ver} && pip install --upgrade pip virtualenv\n"

    dockerfile_content_local += "\n# Creating Virtual Environments and Installing Requirements\n"
    dockerfile_content_local += "WORKDIR /opt/venvs\n\n"

    # Add commands to create venvs and install requirements
    # We group them to reduce layers for better image size
    
    for env_name, py_ver in mapped_tasks:
        req_file = f"/tmp/requirements/{env_name}.txt"
        
        # Command:
        # 1. Switch to specific python version
        # 2. Create venv
        # 3. Activate and install requirements
        cmd = f"""RUN pyenv local {py_ver} && \\
    virtualenv {env_name} && \\
    . {env_name}/bin/activate && \\
    pip install --upgrade pip && \\
    pip install -r /tmp/requirements/{env_name}.txt --upgrade-strategy eager --prefer-binary 

""" if py_ver.startswith("3.") else f"""RUN pyenv local {py_ver} && \\
    virtualenv {env_name} && \\
    . {env_name}/bin/activate && \\
    pip install -r /tmp/requirements/{env_name}.txt --upgrade-strategy eager --prefer-binary 

"""
        dockerfile_content_local += cmd

    # Final cleanup
    dockerfile_content_local += "\n# Cleanup\nRUN rm -rf /tmp\n"
    dockerfile_content_local += "# Reset DEBIAN_FRONTEND\nENV DEBIAN_FRONTEND=\n"
    dockerfile_content_local += "USER root\nWORKDIR /kaggle/working\n"

    with open(DOCKERFILE_PATH, "w", encoding="utf-8") as f:
        f.write(dockerfile_content_local)
    
    print(f"Dockerfile generated at {DOCKERFILE_PATH} with {len(tasks)} environments.")

if __name__ == "__main__":
    generate_dockerfile()