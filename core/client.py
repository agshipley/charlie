import anthropic
import time
import json
from datetime import datetime
from .config import config


def get_client():
    """Return an Anthropic client instance with extended timeout."""
    return anthropic.Anthropic(
        api_key=config.api_key,
        timeout=300.0,  # 5 minute timeout per request
    )


def call_agent(
    system_prompt: str,
    user_message: str,
    tools: list | None = None,
    tool_handlers: dict | None = None,
    model: str | None = None,
    max_tokens: int = 8096,
    max_iterations: int = 20,
) -> dict:
    """
    Run a full agent loop: send a message, handle tool use, repeat until done.
    Prints real-time progress so you always know what's happening.
    """
    client = get_client()
    model = model or config.model_daily
    tools = tools or []
    tool_handlers = tool_handlers or {}
    messages = [{"role": "user", "content": user_message}]
    collected_text = []
    collected_tool_results = []

    for iteration in range(max_iterations):
        _log(f"API call {iteration + 1}/{max_iterations} → {model}")
        start = time.time()

        response = _call_with_retry(
            client, model, system_prompt, tools, messages, max_tokens
        )

        elapsed = time.time() - start
        _log(f"Response in {elapsed:.1f}s — stop_reason: {response.stop_reason}")

        # Add assistant response to history
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    collected_text.append(block.text)
            _log("Agent finished.")
            break

        elif response.stop_reason == "max_tokens":
            # Output was truncated — collect what we have and ask to continue
            for block in response.content:
                if hasattr(block, "text"):
                    collected_text.append(block.text)
            _log("Hit max_tokens — requesting continuation...")
            messages.append({"role": "user", "content": "Your response was truncated. Continue exactly where you left off. Do not restart or repeat — just continue the output."})

        elif response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    _log(f"  Tool: {block.name}")
                    handler = tool_handlers.get(block.name)
                    if handler:
                        result = handler(block.input)
                        collected_tool_results.append({
                            "tool": block.name,
                            "input": block.input,
                            "result": result,
                        })
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result if isinstance(result, str) else json.dumps(result),
                        })
                    elif block.name == "web_search":
                        # Web search is handled by the API itself
                        pass
                    else:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": f"Error: No handler registered for tool '{block.name}'",
                        })

                if hasattr(block, "text") and block.text:
                    # Print a preview of what the agent is thinking
                    preview = block.text[:120].replace("\n", " ")
                    _log(f"  Agent: {preview}...")
                    collected_text.append(block.text)

            if tool_results:
                messages.append({"role": "user", "content": tool_results})

        else:
            _log(f"Unexpected stop_reason: {response.stop_reason}")
            for block in response.content:
                if hasattr(block, "text"):
                    collected_text.append(block.text)
            break

    return {
        "text": "\n".join(collected_text),
        "messages": messages,
        "tool_results": collected_tool_results,
    }


def _call_with_retry(client, model, system, tools, messages, max_tokens, max_retries=5):
    """Call the API with retry logic for rate limits, connection errors, and server errors."""
    for attempt in range(max_retries):
        try:
            kwargs = {
                "model": model,
                "max_tokens": max_tokens,
                "system": system,
                "messages": messages,
            }
            if tools:
                kwargs["tools"] = tools
            return client.messages.create(**kwargs)
        except anthropic.RateLimitError:
            wait_time = 30 * (attempt + 1)
            _log(f"  Rate limit hit, retrying in {wait_time}s ({attempt + 1}/{max_retries})")
            time.sleep(wait_time)
        except anthropic.APIConnectionError as e:
            wait_time = 10 * (attempt + 1)
            _log(f"  Connection error: {e}. Retrying in {wait_time}s ({attempt + 1}/{max_retries})")
            time.sleep(wait_time)
        except anthropic.APIStatusError as e:
            if e.status_code >= 500:
                wait_time = 15 * (attempt + 1)
                _log(f"  Server error ({e.status_code}), retrying in {wait_time}s ({attempt + 1}/{max_retries})")
                time.sleep(wait_time)
            else:
                raise
    raise Exception(f"Max retries ({max_retries}) exceeded")


def _log(msg: str):
    """Print a timestamped log message."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"  [{ts}] {msg}")