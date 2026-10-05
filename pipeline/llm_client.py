"""One wrapper for every LLM: local (Ollama/vLLM) or hosted API. Only the config differs."""
import os  # read api key from .env file
import re  # text cleanup
import time  # for sleep between retries.

from openai import (
    APIConnectionError,
    APIStatusError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,  # error types for each failure kind
    OpenAI,
    RateLimitError,
)

from .errors import ConfigError, PipelineError, ProviderError, RequestTooLargeError


# Remove <think>...</think> blocks, and an unclosed <think> block (a cut-off reply).
# Reasoning models like Qwen3 write their thinking in those tags
def strip_reasoning(text):
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL)
    text = re.sub(r"<think>.*\Z", "", text, flags=re.DOTALL)
    return text.strip()

# reads the retry-after header from a rate-limit response (how many seconds to wait)
def _retry_after(exc):
    try:
        value = exc.response.headers.get("retry-after")
        return float(value) if value is not None else None
    except (AttributeError, ValueError, TypeError):
        return None

# returns True if the error is HTTP 413 or the message says "request too large".
def _too_large(exc):
    msg = str(getattr(exc, "message", "") or exc).lower()
    return getattr(exc, "status_code", None) == 413 or "request too large" in msg

# Call fn(); retry busy/unreachable providers; turn every provider error into a clear PipelineError. BadRequestError is passed through so the caller can decide what to drop and retry.
def call_with_retries(fn, *, model, base_url="", env_var="", retries=5):
    
    last, wait = None, 0.0
    for attempt in range(retries):
        try:
            return fn()
        except AuthenticationError:
            raise ConfigError(f"The API key for '{model}' was rejected."
                              + (f" Check {env_var} in your .env file." if env_var else ""))
        except BadRequestError:
            raise
        except RateLimitError as e:
            if _too_large(e):
                raise RequestTooLargeError(f"The request is too large for '{model}' on this provider.")
            last = e
            wait = _retry_after(e)
            wait = min(wait if wait is not None else 3 * 2 ** attempt, 60)
        except APIConnectionError as e:          # includes timeouts
            last, wait = e, min(2 * 2 ** attempt, 30)
        except InternalServerError as e:
            last, wait = e, min(2 * 2 ** attempt, 30)
        except APIStatusError as e:
            if e.status_code == 413:
                raise RequestTooLargeError(f"The request is too large for '{model}' on this provider.")
            raise PipelineError(f"'{model}' returned an error (HTTP {e.status_code}): {str(e)[:300]}")
        if attempt < retries - 1:
            time.sleep(wait)
    if isinstance(last, RateLimitError):
        raise PipelineError(f"Model '{model}' kept hitting rate limits. Wait a minute and retry.")
    raise ProviderError(f"Could not get a reply from '{model}'" + (f" at {base_url}" if base_url else "")
                        + f" after {retries} attempts. Check your internet connection or that the model server is running.")


class LLM:
    def __init__(self, cfg, client=None):
        self.model = cfg["model"]
        self.base_url = cfg.get("base_url", "")
        self.temperature = cfg.get("temperature", 0.0)
        self.max_tokens = cfg.get("max_tokens")
        self.extra_body = dict(cfg.get("extra_body") or {})
        self.env = cfg.get("api_key_env") or ""
        self.usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
        self.dropped_options = []        # options the provider rejected and we removed (shown as warnings)
        if client is not None:           # tests inject a fake client
            self.client = client
            return
        key = os.getenv(self.env) if self.env else "not-needed"
        if not key:
            raise ConfigError(f"Missing API key: set {self.env} in your .env file.")
        # max_retries=0: our own retry loop (with clear errors) is the only one
        self.client = OpenAI(base_url=self.base_url, api_key=key, timeout=cfg.get("timeout", 300), max_retries=0)

    def chat(self, system, user, json_mode=False, retries=5):
        kwargs = dict(model=self.model, temperature=self.temperature,
                      messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        if self.max_tokens:
            kwargs["max_tokens"] = self.max_tokens
        if self.extra_body:
            kwargs["extra_body"] = dict(self.extra_body)
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        while True:
            try:
                resp = call_with_retries(lambda: self.client.chat.completions.create(**kwargs),
                                         model=self.model, base_url=self.base_url, env_var=self.env, retries=retries)
                break
            except BadRequestError as e:
                # model/provider may not support JSON mode or the extra options: drop them one by one
                dropped = next((k for k in ("response_format", "extra_body") if k in kwargs), None)
                if dropped is None:
                    raise PipelineError(f"'{self.model}' rejected the request: {str(e)[:300]}")
                kwargs.pop(dropped)
                if dropped not in self.dropped_options:
                    self.dropped_options.append(dropped)
        self._track(resp)
        if not getattr(resp, "choices", None):
            raise PipelineError(f"'{self.model}' returned an empty reply.")
        return strip_reasoning(resp.choices[0].message.content or "")

    # adds up how many calls were made and how many tokens were used
    def _track(self, resp):
        self.usage["calls"] += 1
        u = getattr(resp, "usage", None)
        if u is not None:
            self.usage["prompt_tokens"] += getattr(u, "prompt_tokens", 0) or 0
            self.usage["completion_tokens"] += getattr(u, "completion_tokens", 0) or 0
