import requests
import json
from bs4 import BeautifulSoup
import datetime

response = requests.get("https://www.python.org/doc/versions/")
soup = BeautifulSoup(response.text, 'html.parser')

python_versions = {}

for li in soup.select('ul.simple li'):
    # <li><a class="reference external" href="https://docs.python.org/release/3.8.5/">Python 3.8.5</a>, documentation released on 20 July 2020.</li>
    a_tag = li.find('a')
    if not a_tag:
        continue
    
    version_text = a_tag.text.strip()  # "Python 3.8.5"
    version = version_text.replace("Python ", "")  # "3.8.5"

    # Extract date from the text after the link
    # Example: ", documentation released on 20 July 2020."
    full_text = li.get_text()
    if "documentation released on" in full_text:
        # Parse date (e.g., "20 July 2020")
        date_str = full_text.split("documentation released on")[-1].strip().rstrip(".")
        try:
            release_date = datetime.datetime.strptime(date_str, "%d %B %Y")
            python_versions[version] = release_date.strftime("%Y-%m-%d")
            print(f"{version}: {release_date.strftime('%Y-%m-%d')}")
        except ValueError:
            print(f"{version}: Could not parse date '{date_str}'")
    else:
        if "Python " in full_text:
            print(f"{version}: No release date found")

with open("python_versions.json", "w", encoding="utf-8") as f:
    json.dump(python_versions, f, indent=2, ensure_ascii=False)