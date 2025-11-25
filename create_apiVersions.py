import requests
import json
import datetime
from pathlib import Path
import time
from collections import deque
import itertools

with open("/home/b27jin/config.json", "r") as f:
    config = json.load(f)

api_keys = [config["pypi"], config["pypi2"], config["pypi3"], config["pypi4"]]
rate_windows = {key: deque(maxlen=60) for key in api_keys}
key_cycle = itertools.cycle(api_keys)

def acquire_key():
    """Get an API key that hasn't exceeded rate limit"""
    for _ in range(len(api_keys)):
        key = next(key_cycle)
        window = rate_windows[key]
        now = time.time()
        # If this key has made 60 calls in the last 60 seconds, skip it
        if len(window) == 60 and now - window[0] < 60:
            continue  # Try next key
        return key

    # All keys are rate limited, wait for the oldest call to expire
    saturated = [window for window in rate_windows.values() if len(window) == 60]
    if not saturated:
        time.sleep(0.1)
        return acquire_key()

    oldest_call = min(w[0] for w in saturated)
    wait_for = max(0, 60 - (time.time() - oldest_call) + 1)
    time.sleep(wait_for)
    return acquire_key()

with open("/home/b27jin/CodeModernization/kernel.json", "r", encoding="utf-8") as f:
    kernel_content = json.load(f)

session = requests.Session()
base_url = "https://libraries.io/api/pypi/{pkg}"

def record_call(key):
    rate_windows[key].append(time.time())

if __name__ == "__main__":

    for compt, files in kernel_content.items():
        for fname, script_meta in files.items():
            if "ps" in script_meta and script_meta['runtime'] <= 600 and len(script_meta['datasets'])<=1 and "R" not in script_meta:

                submission_date = datetime.datetime.strptime(script_meta["datetime"], "%Y-%m-%dT%H:%M:%S.%fZ")
                
                apis = script_meta.get("api") or []
                # print(apis)

                results_per_file = ""
                for api in apis:
                    api_meta = None
                    url = base_url.format(pkg=api)
                    for attempt in range(3):
                        current_key = acquire_key()
                        try:
                            resp = session.get(url, params={"api_key": current_key, "per_page": 100}, timeout=25)
                            record_call(current_key)
                            if resp.status_code == 429:
                                continue

                            resp.raise_for_status()
                            api_meta = resp.json()
                            break
                        
                        except requests.exceptions.HTTPError as e:
                            if hasattr(e.response, 'status_code') and e.response.status_code == 429:
                                time.sleep(1)
                                continue
                            if attempt == 2:
                                print(f"HTTP error for {api}: {compt}/{fname} - {e}")
                                with open("apiMatch_timeout.json", "a", encoding="utf-8") as json_file:
                                    json_file.write(f"{compt}/{fname}\n")
                            else:
                                time.sleep(1)
                        except requests.exceptions.Timeout:
                            if attempt == 2:
                                with open("apiMatch_timeout.json", "a", encoding="utf-8") as json_file:
                                    json_file.write(f"{compt}/{fname}\n")
                            else:
                                time.sleep(1)
                        except Exception as e:
                            if attempt == 2:
                                print(f"Fetch fail {api}: {compt}/{fname} due to {e}")
                                with open("apiMatch_timeout.json", "a", encoding="utf-8") as json_file:
                                    json_file.write(f"{compt}/{fname}\n")
                                api_meta = None
                            else:
                                time.sleep(1)
                                continue
                    
                    closest_v = None
                    closest_dt = None
                    if api_meta and api_meta["status"] != "Removed":
                        versions = api_meta.get("versions", [])
                        for version in versions:
                            pub_date = datetime.datetime.strptime(version['published_at'], '%Y-%m-%dT%H:%M:%S.%fZ') #'2008-04-25T16:22:32.000Z',

                            if not pub_date:
                                continue

                            if pub_date < submission_date:
                                if closest_dt is None or pub_date > closest_dt:
                                    closest_dt = pub_date
                                    closest_v = version['number']
                        
                        if closest_dt:
                            # print(f"{compt}_{fname} | {api} | {closest_v} | {closest_dt.date()} <= {submission_date.date()}")
                            results_per_file += f"{api}=={closest_v}\n"
                        else:
                            if api_meta is not None: 
                                print(f"{compt}_{fname} | {api} | no version <= submission_date")
                                with open("apiMatch_timeout.json", "a", encoding="utf-8") as json_file:
                                        json_file.write(f"{compt}_{fname} | {api} | no version <= submission_date\n")
                    
                with open(f"/home/b27jin/CodeModernization/apiDegradeList/{compt}_{fname.split('.')[0]}.txt", "w", encoding="utf-8") as f:
                    f.writelines(results_per_file)
