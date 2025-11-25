import json
import datetime
from tqdm import tqdm

with open("CodeModernization/kernel.json", "r", encoding="utf-8") as f:
    kernel_content = json.load(f)

with open("CodeModernization/apiDowngrade/python_versions.json", "r", encoding="utf-8") as f:
    python_versions = json.load(f)

if __name__ == "__main__":
    for compt, files in tqdm(kernel_content.items(), total=len(kernel_content),
            desc="Competitions",
            position=0):
            for fname, script_meta in tqdm(files.items(), total=len(files),
                desc=f"submissions to {compt}",
                leave=False,
                position=1):
                if "ps" in script_meta and script_meta['runtime'] <= 600 and len(script_meta['datasets'])<=1 and "R" not in script_meta:
                    submission_date = datetime.datetime.strptime(script_meta["datetime"], "%Y-%m-%dT%H:%M:%S.%fZ")