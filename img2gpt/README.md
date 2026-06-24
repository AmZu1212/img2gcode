# img2gpt

Converts a portrait image into coloring-book style line art using the OpenAI Image API.

Basic run:

```powershell
python img2gpt\img2gpt.py --input "source images\nir test.png"
```

By default, outputs are written to `img2gpt/history/`.

The script reads the API key from `OPENAI_API_KEY` first, then falls back to `img2gpt/GPT_API_Key.txt`.

Defaults are tuned for better image quality:

- `--model gpt-image-2`
- `--quality medium`
- `--size 1024x1536`
