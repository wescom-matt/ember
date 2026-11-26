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
# qwen3.5-9b-8k  (optional, user-selectable; same model with a bigger memory window)
FROM qwen3.5:9b
PARAMETER num_ctx 8192
PARAMETER presence_penalty 1.5
PARAMETER temperature 1
PARAMETER top_k 20
PARAMETER top_p 0.95
```

Speed sample on the P1 (Quadro T1000 4 GB, 2026-11-25; about a third of the model fits on the GPU, the rest runs on
the CPU): both write about 4-4.6 tokens/s. A turn that fills the window takes about 50 s to the first word on 4k
(3,300 prompt tokens) and about 102 s on 8k (6,500 prompt tokens). Re-measure in Ember: Workshop > Models.

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
