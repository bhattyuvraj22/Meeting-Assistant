import json  # to convert json string to python dict
import re  # to strip the markdown fences ```

# extarct_json extarct json object from the llm reposne 

def extract_json(text):
    """Pull the first JSON object out of a model reply (tolerates ``` fences and chatter around it)."""
    text = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object found")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("JSON reply is not an object")
    return data
