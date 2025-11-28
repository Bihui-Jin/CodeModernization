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
- Review and run the provided Docker scripts to familiarize yourself with the environment.
- Inspect a few Kaggle notebooks to give yourself a general idea about its task/target metric.
- Set up MLE-Bench (lite) locally on the school's server.
- Begin scaffolding your execution/repair pipeline (ideally).

## **Procedure**

### Raw Data Collection
```KaggleApi().authenticate``` requires to log into kaggle

```fetch/competitions.txt``` contains the list of research competitions

[Kaggle Python Docker images (CPU-only and GPU)](https://github.com/Kaggle/docker-python) allow users to run a Python Notebook in the cloud against their competitions and datasets without having to download data or set up the environment. (Python 3.11.13)

1. ```fetch/get_content.py``` crawls htmls of the (1) metadata of the mian page, (2) version list of submissions made by the same user to a submission, and (3) code content of a submission version via selenium
    - output: 
        - ```fetch/competitions/{competition}/meta_html/{submissionID}_{status}.htlm```: metadata of the mian page including the submission date, score info, running time, usage of external dependencies, etc.
        - ```fetch/competitions/{competition}/version_list_html/{submissionID}_{status}.htlm```: version List HTML
        - ```fetch/competitions/{competition}/html/{submissionID}_{status}.htlm```: code content HTML of a submission version
        - ```fetch/failed_kernels.txt```: the kernels that is empty or has no key content found
        - ```fetch/crashed_kernel.txt```: failed to load htmls via the driver
        - ```fetch/competitions_done.txt```: completed competitions for collection

    where {competition} is the competition name, </br>{submissionID} integrates the user name and the notebook name using "_" ({userName_notebookName}), </br>and {status} (e.g., C1: representing the successful complied code on kaggle) combines the script type (C: code, S: JSON script, O: Ops neither C nor S) with the script status (0: Failed compiling on kaggle, 1: Success, 2: Cancelled compilation).

2. ```fetch/get_kernels.py``` fetches notebooks (kernels/submissions) related to the competition
    - output: ```fetch/competitions/{competition}/kernels.txt```


### Baseline (replicating of collected scripts)
#### Raw Data Processing
1. ```create_kernel.py``` retrieves metadata (runtime, submission date, APIs, private score, and external dataset) for all executable scripts 
    - Use pigar (still updated) to dynamically list dependencies with correct PyPI names
    - output: ```kernel.json```

2. ```baseline/create_fullDataset.py``` filters out targeted htmls and converts the code in html to python code in notebooks (```.ipynb```)
    - output: ```baseline/scripts/{competition}_{submissionID}_{status}.ipynb```

    <span style="color: red;">**Make sure to run ```create_kernel.py``` before going through the below sections**</span>

3. ```baseline/check_missingAPIs.py``` inspects any APIs not found in the kaggle image
    - prerequisite: ```apiDowngrade/api_chche.json``` from ```apiDowngrade/create_apiVersions.py```
    - output:  ```baseline/requirements.txt```
    - details: Found 906 packages in Docker image</br>
    416 packages in cache</br>
    Found 285 packages in cache but not in Docker image where 19 (Mask-Face-Inference, TMLF, base_atlas, cargo-aidoc, celltraj-copperma, drl-model, gender-classifier-cnn-usoltsev37, ingradient-lib-temp2, matplotlib-arm64, mis-modulos, mmseg, motifcal, multi-emotion-recognition, package-generator, ptmchat, rcnnmasks, reco, umap, webcrawl) are incompactible (depends on non-existent packages, no satisfied version, failed to build wheel, and generating package metadata) with the env of the kaggle image</br>
    Filter out these packages for valid reasons and they are not supported by Kaggle

4. ```baseline/search_nltkCorpora.py``` searches all nltk packages used in the scripts
    - output: ```baseline/nltkCorpora.txt```
    - details: 550 scripts use nltk (11 unique corpora)

#### Execution
Please refer to the [section here](#execute-baseline)

### API Downgrade
Downgrade dependency versions (Rule-based: looking for old version APIs in pypi):
1. For each dependency, query Libraries.io/PyPI for the version current at (or just before) the notebook’s original submit date.
2. Create one docker image for the submissions under the same user&competition (choose the oldest version if conflicts). 
3. Pin environment to those historical versions and execute the notebook.
4. If failures arise, apply the same cell-level repair loop, but favor backward-compatible edits that align with older APIs.
#### API Preparation
1. ```apiDowngrade/create_apiVersions.py``` creates api match list based on the script submission date.
    - prerequisite: load ```api_keys``` (API Key(s) from [libraries.io](https://libraries.io/api)) from user's ```config```. 

    - output:  
        - ```apiDowngrade/api_chche.json```: API metadata to save time in API retrieval

        - ```apiDowngrade/apiDowngradeList/{competition_fileName}.txt```: the list of API names and their match stable API versions (in the format of api==version) for each submission

        (record competition name, submission name, and API name)
        - ```apiDowngrade/apiMatch_notFound.txt```: no API version available

        - ```apiDowngrade/apiMatch_notFound.txt```: no API publishing date < submission date available (select the oldest version)
        
        - ```apiDowngrade/apiMatch_notFound.txt```: timeout of calling libraries.io API

2. ```apiDowngrade/python_versions.py``` crawles the python version w.r.t. its release date from the [Python's offical](https://www.python.org/doc/versions/)
    - output: ```apiDowngrade/python_versions.json```

3. ```apiDowngrade/python_versions_update.py``` update each submisson in ```kernel.json``` with relative python versions
    - feature: discern the code syntax (py2 or py3) 
    - output: updated ```apiDowngrade/kernel_w_pyVersion.json```

    <details>
    <summary> Python Version Statistics </summary>

    **Total scripts updated:** 13011  
    **Scripts with no match:** 0  
    **Total unique versions:** 76

    ###### Python Version Distribution

    | Python Version | Count | Percentage |
    |----------------|-------|------------|
    | 3.13.2 | 117 | 0.90% |
    | 3.13.1 | 172 | 1.32% |
    | 3.13.0 | 89 | 0.68% |
    | 3.12.7 | 14 | 0.11% |
    | 3.12.6 | 73 | 0.56% |
    | 3.12.5 | 80 | 0.61% |
    | 3.12.4 | 228 | 1.75% |
    | 3.12.3 | 395 | 3.04% |
    | 3.12.2 | 254 | 1.95% |
    | 3.12.1 | 545 | 4.19% |
    | 3.12.0 | 375 | 2.88% |
    | 3.11.9 | 62 | 0.48% |
    | 3.11.7 | 20 | 0.15% |
    | 3.11.5 | 239 | 1.84% |
    | 3.11.4 | 743 | 5.71% |
    | 3.11.3 | 412 | 3.17% |
    | 3.11.2 | 439 | 3.37% |
    | 3.11.1 | 923 | 7.09% |
    | 3.11.0 | 296 | 2.27% |
    | 3.10.14 | 225 | 1.73% |
    | 3.10.8 | 23 | 0.18% |
    | 3.10.7 | 222 | 1.71% |
    | 3.10.6 | 209 | 1.61% |
    | 3.10.5 | 805 | 6.19% |
    | 3.10.4 | 563 | 4.33% |
    | 3.10.3 | 159 | 1.22% |
    | 3.10.2 | 437 | 3.36% |
    | 3.10.1 | 262 | 2.01% |
    | 3.10.0 | 190 | 1.46% |
    | 3.9.15 | 107 | 0.82% |
    | 3.9.13 | 145 | 1.11% |
    | 3.9.9 | 143 | 1.10% |
    | 3.9.8 | 41 | 0.32% |
    | 3.9.7 | 10 | 0.08% |
    | 3.9.6 | 82 | 0.63% |
    | 3.9.5 | 90 | 0.69% |
    | 3.9.4 | 19 | 0.15% |
    | 3.9.2 | 58 | 0.45% |
    | 3.9.1 | 38 | 0.29% |
    | 3.9.0 | 122 | 0.94% |
    | 3.8.7 | 125 | 0.96% |
    | 3.8.6 | 63 | 0.48% |
    | 3.8.5 | 280 | 2.15% |
    | 3.8.4 | 95 | 0.73% |
    | 3.8.3 | 144 | 1.11% |
    | 3.8.2 | 3 | 0.02% |
    | 3.8.1 | 61 | 0.47% |
    | 3.8.0 | 2 | 0.02% |
    | 3.7.12 | 177 | 1.36% |
    | 3.7.10 | 16 | 0.12% |
    | 3.7.9 | 118 | 0.91% |
    | 3.7.8 | 76 | 0.58% |
    | 3.7.7 | 124 | 0.95% |
    | 3.7.5 | 5 | 0.04% |
    | 3.7.4 | 150 | 1.15% |
    | 3.7.3 | 581 | 4.47% |
    | 3.7.2 | 79 | 0.61% |
    | 3.7.1 | 48 | 0.37% |
    | 3.7.0 | 174 | 1.34% |
    | 3.6.9 | 46 | 0.35% |
    | 3.6.5 | 77 | 0.59% |
    | 3.6.4 | 61 | 0.47% |
    | 3.6.3 | 99 | 0.76% |
    | 3.6.1 | 3 | 0.02% |
    | 3.6.0 | 45 | 0.35% |
    | 3.5.10 | 307 | 2.36% |
    | 3.5.9 | 107 | 0.82% |
    | 3.5.8 | 3 | 0.02% |
    | 3.5.7 | 25 | 0.19% |
    | 3.5.6 | 252 | 1.94% |
    | 3.5.5 | 67 | 0.51% |
    | 3.5.3 | 41 | 0.32% |
    | 3.5.2 | 95 | 0.73% |
    | 2.7.18 | 22 | 0.17% |
    | 2.7.16 | 9 | 0.07% |
    | 2.7.15 | 5 | 0.04% |
    </details>
#### Execution
Please refer to the [section here](#execute-downgrade)

### Execution (in Docker) 
#### Image Preparation
We use only the last y in each 2/3.x.y version, as Python follows pretty well with semantic versioning and there is usually no API change in y versions

```docker/create_venv.py``` creates a docker file used to build an unified docker image that integrates multiple python virtual environments for all submissions to handle the issues of multiple python versions and different API versions required by every submission.
- prerequisite: (1)```baseline/requirements.txt```, </br>(2)```baseline/nltk_corpora.txt```, </br>(3)```apiDowngrade/kernel_w_pyVersion.json```, </br>(4)files under ```apiDowngrade/apiDowngradeList/*.txt```, and</br>(5)docker image ```gcr.io/kaggle-gpu-images/python```
- output: ```docker/Dockerfile.base```
- execution: ```DOCKER_BUILDKIT=0 docker build --platform=linux/amd64 -t kaggle_coding -f docker/Dockerfile.base .```
- Note: install libzstd-dev to build Python 3.14 or newer but Ubuntu 20.04 does not include a sufficiently new version of this package to build the `compression.zstd` module.

When building the image, TMLF fails to install as it requires Python >= 3.12, which is higher than kaggle's provided Python 3.11.13

<a id="execute-baseline"></a>
#### Baseline
- `Dockerfile.base` → build the base image with pinned toolchains.
- `run_docker_w_time.py` → execute notebooks in containers and capture wall-clock runtime, logs, and exit status.
- `run_docker_w_time_parallel.py` → execute notebooks in parallel and capture wall-clock runtime, logs, and exit status.
- **`run_docker_w_time_erroredout.py` → tell me what it is based on your understanding. I'll ask you on this Friday.**
- Saves output back to the kaggle script

<a id="execute-downgrade"></a>
#### API Downgrade

#### Metrics
- Pass Rate: fraction of notebooks that execute to completion without csv generated (and valid csv).
- Replication Rate: replicated score relative to the notebook’s original reported score.
- Runtime: end-to-end execution time per notebook/run (upgrade vs. downgrade conditions).

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