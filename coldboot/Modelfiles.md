# Custom model recipes (captured from the P1, 2026-11-25)

ColdBoot rebuilds these from `models.json` through Ollama's `/api/create`.
The same thing as plain Modelfiles, if you ever need `ollama create -f`:

```
# qwen3.5-9b-4k
FROM qwen3.5:9b
PARAMETER num_ctx 4096
PARAMETER presence_penalty 1.5
PARAMETER temperature 1
PARAMETER top_k 20
PARAMETER top_p 0.95
```

```
# llama3.2-4k
FROM llama3.2:latest
PARAMETER num_ctx 4096
PARAMETER stop <|start_header_id|>
PARAMETER stop <|end_header_id|>
PARAMETER stop <|eot_id|>
```

```
# llama3.2-1b-4k
FROM llama3.2:1b
PARAMETER num_ctx 4096
```

Templates, licenses and system prompts come unchanged from the base model.
`nomic-embed-text:v1.5` is Nomad's embedder and is used as-is.
