import anthropic
import time
import json
from .config import config


def get_client():
    """Return an Anthropic client instance."""
    return anthropic.Anthropic(api_key=config.api_key)


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

    Args:
        system_prompt: The system prompt defining agent behavior.
        user_message: The initial user message that kicks off the agent.
        tools: List of tool definitions (including web_search if needed).
        tool_handlers: Dict mapping tool names to handler functions.
            Each handler receives the tool input dict and returns a string result.
        model: Which model to use. Defaults to config.model_daily.
        max_tokens: Max tokens per response.
        max_iterations: Safety limit on agent loop iterations.

    Returns:
        dict with:
            - "text": The final text output from the agent.
            - "messages": Full conversation history.
            - "tool_results": List of all tool results collected.
    """
    client = get_client()
    model = model or config.model_daily
    tools = tools or []
    tool_handlers = tool_handlers or {}
    messages = [{"role": "user", "content": user_message}]
    collected_text = []
    collected_tool_results = []

    for iteration in range(max_iterations):
        # Retry loop for rate limits
        response = _call_with_retry(
            client, model, system_prompt, tools, messages, max_tokens
        )

        # Add assistant response to history
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            # Agent is done — collect final text
            for block in response.content:
                if hasattr(block, "text"):
                    collected_text.append(block.text)
            break

        elif response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
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
                        # Web search is handled by the API itself — no handler needed
                        pass
                    else:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": f"Error: No handler registered for tool '{block.name}'",
                        })

                # Also collect any text blocks in tool_use responses
                if hasattr(block, "text"):
                    collected_text.append(block.text)

            if tool_results:
                messages.append({"role": "user", "content": tool_results})

        else:
            # Unexpected stop reason
            for block in response.content:
                if hasattr(block, "text"):
                    collected_text.append(block.text)
            break

    return {
        "text": "\n".join(collected_text),
        "messages": messages,
        "tool_results": collected_tool_results,
    }


def _call_with_retry(client, model, system, tools, messages, max_tokens, max_retries=3):
    """Call the API with retry logic for rate limits."""
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
            print(f"  Rate limit hit, waiting {wait_time}s (attempt {attempt + 1}/{max_retries})...")
            time.sleep(wait_time)
    raise Exception("Max retries exceeded for rate limit")
