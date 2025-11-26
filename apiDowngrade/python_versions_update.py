import json
import datetime
from tqdm import tqdm
from collections import Counter

with open("kernel.json", "r", encoding="utf-8") as f:
    kernel_content = json.load(f)

with open("apiDowngrade/python_versions.json", "r", encoding="utf-8") as f:
    python_versions = json.load(f)

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
                    submission_date = datetime.datetime.strptime(script_meta["datetime"], "%Y-%m-%dT%H:%M:%S.%fZ")

                    # Find the most recent Python version released before submission_date
                    best_version = None
                    best_date = None
                    
                    for version, release_date in python_versions_dt.items():
                        if release_date < submission_date:
                            if best_date is None or release_date > best_date:
                                best_date = release_date
                                best_version = version
                    
                    if best_version:
                        script_meta["python"] = best_version
                        python_version_counts[best_version] += 1
                        updated_count += 1
                    else:
                        no_match_count += 1
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


