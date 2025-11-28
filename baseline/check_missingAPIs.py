import json
import subprocess
import sys

image_name = "gcr.io/kaggle-gpu-images/python"
cached_apis = "apiDowngrade/api_cache.json"
save_path = "baseline/requirements.txt"

def get_docker_packages(image_name):
    """Get list of installed packages from Docker image."""
    print(f"Fetching packages from Docker image: {image_name}")
    try:
        # Run docker and execute pip list
        cmd = [
            "docker", "run", "--rm", image_name,
            "pip", "list", "--format=json"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        packages = json.loads(result.stdout)
        
        # Extract package names (normalize to lowercase)
        docker_packages = {pkg["name"].lower() for pkg in packages}
        print(f"Found {len(docker_packages)} packages in Docker image")
        return docker_packages
    
    except subprocess.CalledProcessError as e:
        print(f"Error running docker command: {e}")
        print(f"Stderr: {e.stderr}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error parsing pip list output: {e}")
        sys.exit(1)

def get_cached_packages(cache_path="apiDowngrade/api_cache.json"):
    """Get list of package names from api_cache.json."""
    print(f"Reading cached packages from: {cache_path}")
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            api_cache = json.load(f)
        
        # Extract package names 
        cached_packages = {name for name in api_cache.keys()}
        print(f"Found {len(cached_packages)} packages in cache")
        return cached_packages
    
    except FileNotFoundError:
        print(f"Error: Cache file not found at {cache_path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error parsing cache file: {e}")
        sys.exit(1)

def find_missing_packages(docker_packages, cached_packages):
    """Find packages in cache but not in Docker image."""
    missing = cached_packages - docker_packages
    print(f"\nFound {len(missing)} packages in cache but not in Docker image")
    return sorted(missing)

def save_requirements(missing_packages, output_path):
    """Save missing packages to requirements.txt."""
    print(f"\nSaving missing packages to: {output_path}")
    
    # Ensure directory exists
    import os
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        for pkg in sorted(missing_packages):
            f.write(f"{pkg}\n")
    
    print(f"Successfully saved {len(missing_packages)} package names")

def main():
    # Step 1: Get packages from Docker image
    docker_packages = get_docker_packages(image_name)
    
    # Step 2: Get cached packages
    cached_packages = get_cached_packages(cached_apis)
    
    # Step 3: Find missing packages
    missing_packages = find_missing_packages(docker_packages, cached_packages)
    
    # Print some examples
    if missing_packages:
        print("\nExample missing packages:")
        for pkg in missing_packages[:10]:
            print(f"  - {pkg}")
        if len(missing_packages) > 10:
            print(f"  ... and {len(missing_packages) - 10} more")
    
    # Step 4: Save to requirements.txt
    save_requirements(missing_packages, save_path)
    
    print("\nDone!")

if __name__ == "__main__":
    main()