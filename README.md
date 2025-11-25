# CodeModernization
LLM-Assisted Bug Fixing, API Adjustment, and Replication via Kaggle Scripts


**Venue:** ISSTA 2026 (submission deadline: January 29, 2026)
**Objective:** Evaluate LLMs’ ability to 
 - (i) fix code broken by dependency/API drift, 
 - (ii) adjust to API changes (upgrade/downgrade), and 
 - (iii) replicate original results from historical Kaggle notebooks.

I provided:
 - (1) [Environment & tooling](https://github.com/Bihui-Jin/CodeModernization/tree/main/docker): Dockerfile(s) and run scripts.
 - (2) [Workloads](https://github.com/Bihui-Jin/CodeModernization/tree/main/notebooks): Historical Kaggle notebooks (with release dates, scores, and runtimes) and
 - (3) [API Tutorial](https://libraries.io/api): Versions and release dates from Libraries.io (PyPI APIs)

**Aim:** Use real ML pipeline code from Kaggle notebooks (circa ~2015–2019) to systematically upgrade and downgrade dependency versions, then assess how well LLMs repair resulting breakages and preserve behavior/performance.

**Background:**
- [Notebook](https://github.com/Bihui-Jin/CodeModernization/tree/main/notebooks): Executable document composed of ordered code cells.
- [Docker](https://github.com/Bihui-Jin/CodeModernization/tree/main/docker): Isolated container (sub-os) environment that runs tasks in a different environment; changes do not affect your host system.
- [MLE-Bench (lite)](https://github.com/openai/mle-bench): Curated competition tasks/datasets for ML evaluation.
- API Deprecation: Older scripts often fail due to package updates (renamed/removed functions, changed defaults, etc.).
- [Libraries.io / PyPI](https://libraries.io/api): Sources for dependency version history and release timestamps (e.g., try to call https://libraries.io/api/pypi/<dependency_name>?api_key=<xxx>&per_page=100). see details at https://libraries.io/api


**Expectations** for this week:
- Review and run (maybe?) the provided Docker scripts to familiarize yourself with the environment.
- Inspect a few Kaggle notebooks to give yourself a general idea about its task/target metric.
- Set up MLE-Bench (lite) locally on the school's server.
- Begin scaffolding your execution/repair pipeline (ideally).

## **Procedure**

### Raw Data Collection
- ```KaggleApi().authenticate``` requires to log into kaggle

- ```fetch/competitions.txt``` contains the list of research competitions

- ```fetch/get_content.py``` crawls htmls of the (1) metadata of the mian page, (2) version list of submissions made by the same user to a submission, and (3) code content of a submission version via selenium
    - output: 
        - ```fetch/competitions/{competition}/meta_html/{submission}.htlm```: metadata of the mian page including the submission date, score info, running time, usage of external dependencies, etc.
        - ```fetch/competitions/{competition}/version_list_html/{submission}.htlm```: version List HTML
        - ```fetch/competitions/{competition}/html/{submission}.htlm```: code content HTML of a submission version
        - ```fetch/failed_kernels.txt```: the kernels that is empty or has no key content found
        - ```fetch/crashed_kernel.txt```: failed to load htmls via the driver
        - ```fetch/competitions_done.txt```: completed competitions for collection

- ```fetch/get_kernels.py``` fetches notebooks (kernels/submission) related to the competition
    - output: ```fetch/competitions/{competition}/kernels.txt```

#### File collected: 
- ```fetch/competitions_done.txt```:
- ```fetch/{competition}``` contains the html for submissions in the related competition
    - ```html```:
    - ```meta_html```:
    - ```version_list_html```:
    - ```kernels.txt```:



### Raw Data Processing
- filters out targeted htmls
- converts htmls to notebooks (```.ipynb```)

### Baseline Script Run
- Kaggle images
- build a new image to include extr corpus
- Docker run

### Runtime Result Processing
- ```create_kernel.py```: retrieve metadata about targeted scripts (executable, w/ private score, runtime <= 600s)
    - output: ```kernel.json```

### API Downgrade
- ```apiDowngrade/create_apiVersions.py```: create api match list based on the script submission date.
    - prerequisite: load ```api_keys``` (API Key(s) from [libraries.io](https://libraries.io/api)) from user's ```config```. 

    - output:  
        - ```api_chche.json```: API metadata to save time in API retrieval

        - ```apiDowngrade/apiDowngradeList/{competition_fileName}.txt```: the list of API names and their match API versions (api==version) for each submission

        (record competition name, submission name, and API name)
        - ```apiMatch_notFound.txt```: no API version available

        - ```apiMatch_notFound.txt```: no API publishing date < submission date available (select the oldest version)
        
        - ```apiMatch_notFound.txt```: timeout of calling libraries.io API
- 

### API Upgrade

1. Replcation: Execute the .ipynb file inside Docker to collect pass rate and replicated score.
    - 1. Replicable: have valid csv generated
       * i. filtering criteria:
         ```math
         |\frac{measured\:score - reported\:score}{reported\:score}| \leq \tau
         ```
         where tau = 5% for now, meaning that scripts whose replicated scores differ from their Kaggle-reported scores (the variancere) by less than 5% advance to the next round.
         
    - 2. For those non-replicable: do following
2. Upgrade:
    - 1. File-level:
       * i. Convert notebooks (`.ipynb`) to python (`.py`) files via nbconvert.
       * ii. Execute the `.py` file inside Docker.
       * iii. On failure, prompt the LLM w/ the exception to update code to current APIs without altering algorithmic structure (data flow, feature engineering steps, etc.). 
    - 2. Cell-level:
       * i. Execute the notebook w/o caring the errors (use `--ExecutePreprocessor.allow_errors=True`).
       * ii. If errors occur, localize the first failing cell.
       * iii. Prompt the LLM with all cells up to (and including) the failing one and the exception of the failing cell (no output of other cells); request API-compatible edits with minimal structural change.
       * iv. Re-execute; repeat until the notebook runs cleanly or time budget cap is reached.
3. Downgrade dependency versions (Rule-based: looking for old version APIs in pypi):
    - 1. For each dependency, query Libraries.io/PyPI for the version current at (or just before) the notebook’s original submit date.
    - 2. Pin environment to those historical versions and execute the notebook.
    - 3. If failures arise, apply the same cell-level repair loop, but favor backward-compatible edits that align with older APIs.

**Execution (in Docker):**
- `Dockerfile.base` → build the base image with pinned toolchains.
- `run_docker_w_time.py` → execute notebooks in containers and capture wall-clock runtime, logs, and exit status.
- `run_docker_w_time_parallel.py` → execute notebooks in parallel and capture wall-clock runtime, logs, and exit status.
- **`run_docker_w_time_erroredout.py` → tell me what it is based on your understanding. I'll ask you on this Friday.**
- Saves output back to the kaggle script

**Metrics** (what we need to collect and compare with):
- Pass Rate: fraction of notebooks that execute to completion without csv generated (and valid csv).
- Replication Rate: replicated score relative to the notebook’s original reported score.
- Runtime: end-to-end execution time per notebook/run (upgrade vs. downgrade conditions).


**Notebook Info**
- [notebooks_w_output](./notebooks_w_output): executed scripts that output has been written back to the notebook.
- [sampled_notebook_info](./sampled_notebook_info.json): key - filename, value - 
    - "is_buggy": true, # whether the script has a csv generated
    - "passed": false, # whether the script has a csv generated
    - "measured_score": null, # the score after evaluating the csv file generated by replicating the script
    - "reported_score": 0.4013, # the score that shows on Kaggle's web
    - "replicable": false, # whether tau <= 5%
    - "thrus": null, # tau value
    - "creation": "10/13/2023" # creation date of the script in the format of mm/dd/yyyy
- [callable LLM portal](./LLMs/plan_and_code_query.py): use `plan_and_code_query` to interact with LLMs. Parameters need to pass in:
    - LLM_model: model name, e.g., "gpt-5"
    - sys_prompt: system prompt instructed by 
        - \# Role
        - \# Task
        - \# Input
            - e.g., - code solution: the buggy code in the `.py` python or `.ipynb` notebook format
            - e.g., - exception: the exception message triggered by the code solution
        - \# Output
            - e.g., Your response should be a brief plan of your proposed solution in natural language (3-5 sentences), followed by a single markdown code block (wrapped in ```) which implements the bugfix. There should be no additional headings or text in your response. Just natural language text followed by a newline and then the markdown code block. 
    - usr_prompt: user prompt instructed by
        - \# code solution

        \`\`\`

        \<code here>

        \`\`\`
        - \# exception

        \`\`\`

        \<exception msg here>

        \`\`\`
        - Note: remember to use ```
- OpenAI API Key: OpenAI API key is used to verify yourself and call the ChatGPT model family.
    - Note: you need to set the key as your env variable, i.e., 
    - export OPENAI_API_KEY="\<key here>"