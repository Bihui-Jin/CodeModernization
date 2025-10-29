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

**Procedure:**
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
