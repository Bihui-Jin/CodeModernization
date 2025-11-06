from CodeModernization.LLMs.query import query
from CodeModernization.LLMs.utils import extract_code, extract_text_up_to_code

def plan_and_code_query(LLM_model, sys_prompt, usr_prompt, temperature=0.1, retries=3) -> tuple[str, str]:
    """Generate a natural language plan + code in the same LLM call and split them apart."""
    completion_text = None

    query_kwargs = {
        "system_message": sys_prompt,
        "user_message": usr_prompt,
        "model": LLM_model, ##LLM model name, e.g., "gpt-5"
        "convert_system_to_user": False, # by default
    }

    if query_kwargs["model"] != "gpt-5":
        query_kwargs["temperature"] = temperature

    # if self.acfg.code.model == "qwen3-max":
    #     query_kwargs["base_url"] = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

    print(f"Model {query_kwargs['model']} is used")

    for _ in range(retries):
        completion_text = query(**query_kwargs)

        code = extract_code(completion_text)
        nl_text = extract_text_up_to_code(completion_text)

        if code and nl_text:
            # merge all code blocks into a single string
            return nl_text, code

        print("Plan + code extraction failed, retrying...")
    print("Final plan + code extraction attempt failed, giving up...")
    return "", completion_text