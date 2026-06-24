"""Convert a portrait photo into coloring-book style line art with OpenAI."""

from __future__ import annotations

import argparse
import base64
import os
from datetime import datetime
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_PROMPT_FILE = SCRIPT_DIR / "prompts" / "coloring_book.txt"
DEFAULT_KEY_FILE = SCRIPT_DIR / "GPT_API_Key.txt"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "history"


def safe_stem(path: Path) -> str:
    return "_".join(path.stem.split())


def timestamp() -> str:
    return datetime.now().strftime("%H-%M_on_%Y-%m-%d")


def load_api_key(key_file: Path) -> str:
    env_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if env_key:
        return env_key

    if not key_file.exists():
        raise FileNotFoundError(
            "OpenAI API key not found. Set OPENAI_API_KEY or create "
            f"{key_file}."
        )

    key_text = key_file.read_text(encoding="utf-8").strip()
    if "=" in key_text and key_text.split("=", 1)[0].strip() == "OPENAI_API_KEY":
        key_text = key_text.split("=", 1)[1].strip()

    key_text = key_text.strip().strip('"').strip("'")
    if not key_text:
        raise ValueError(f"OpenAI API key file is empty: {key_file}")
    return key_text


def load_prompt(prompt_file: Path) -> str:
    if not prompt_file.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_file}")
    prompt = prompt_file.read_text(encoding="utf-8").strip()
    if not prompt:
        raise ValueError(f"Prompt file is empty: {prompt_file}")
    return prompt


def default_output_path(input_path: Path) -> Path:
    return unique_path(
        DEFAULT_OUTPUT_DIR / f"{safe_stem(input_path)}_coloring_{timestamp()}.png"
    )


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate

    raise FileExistsError(f"Could not find an unused output path for {path}")


def convert_image(
    input_path: Path,
    output_path: Path,
    prompt: str,
    api_key: str,
    model: str,
    size: str,
    quality: str,
) -> None:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise SystemExit(
            "The OpenAI Python SDK is not installed. Run: "
            "python -m pip install openai"
        ) from exc

    client = OpenAI(api_key=api_key)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with input_path.open("rb") as image_file:
        result = client.images.edit(
            model=model,
            image=image_file,
            prompt=prompt,
            size=size,
            quality=quality,
        )

    image_base64 = result.data[0].b64_json
    output_path.write_bytes(base64.b64decode(image_base64))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a portrait into coloring-book style line art."
    )
    parser.add_argument("--input", required=True, help="Input portrait image path.")
    parser.add_argument("--output", help="Output PNG path.")
    parser.add_argument(
        "--prompt-file",
        default=str(DEFAULT_PROMPT_FILE),
        help="Prompt text file.",
    )
    parser.add_argument(
        "--api-key-file",
        default=str(DEFAULT_KEY_FILE),
        help="Fallback API key file. OPENAI_API_KEY takes precedence.",
    )
    parser.add_argument("--model", default="gpt-image-2")
    parser.add_argument("--size", default="1024x1536")
    parser.add_argument(
        "--quality", default="medium", choices=["low", "medium", "high", "auto"]
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = Path(args.input).resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input image not found: {input_path}")

    output_path = Path(args.output).resolve() if args.output else default_output_path(input_path)
    prompt = load_prompt(Path(args.prompt_file).resolve())
    api_key = load_api_key(Path(args.api_key_file).resolve())

    convert_image(
        input_path=input_path,
        output_path=output_path,
        prompt=prompt,
        api_key=api_key,
        model=args.model,
        size=args.size,
        quality=args.quality,
    )

    print(f"coloring_output={output_path}")


if __name__ == "__main__":
    main()
