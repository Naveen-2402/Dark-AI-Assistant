import os
from typing import Iterable, Tuple, Union
from dotenv import load_dotenv
from openai import AzureOpenAI

load_dotenv(override=True)


def get_client() -> AzureOpenAI:
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")
    if not endpoint or not api_key:
        raise RuntimeError("Missing AZURE_OPENAI_ENDPOINT or AZURE_OPENAI_API_KEY in environment.")
    return AzureOpenAI(azure_endpoint=endpoint, api_key=api_key, api_version=api_version)


def stream_chat_completion(
    messages,
    temperature: float = 0.7,
    top_p: float = 1.0,
    max_tokens: int = None,
) -> Iterable[Tuple[str, Union[str, None]]]:
    """
    Yields (text_piece, finish_reason).
    - text_piece: a chunk of assistant text
    - finish_reason: None normally, or a string when the model ends
      (e.g., "stop", "length", "content_filter")
    """
    client = get_client()
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

    stream = client.chat.completions.create(
        model=deployment,
        messages=messages,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        stream=True,
    )

    for chunk in stream:
        try:
            choice = chunk.choices[0]

            # Handle text content
            delta = getattr(choice, "delta", None)
            if delta and getattr(delta, "content", None):
                yield delta.content, None

            # Handle finish_reason (end of response)
            if getattr(choice, "finish_reason", None):
                yield "", choice.finish_reason

        except Exception:
            # Ignore malformed chunks (like tool calls or empty deltas)
            continue
