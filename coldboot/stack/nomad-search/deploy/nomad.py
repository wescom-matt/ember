"""Nomad profile: local Ollama + Qwen 3.5 9B, approval required, offline."""
from interpreter import interpreter

interpreter.offline = True
interpreter.auto_run = False
# Local models work more reliably when they write markdown code blocks
# that Open Interpreter then shows for approval, rather than native tools.
interpreter.llm.model = "ollama/qwen3.5:9b"
interpreter.llm.api_base = "http://127.0.0.1:11434"
interpreter.llm.api_key = "ollama"
interpreter.llm.temperature = 0
interpreter.llm.context_window = 8192
interpreter.llm.max_tokens = 2048
interpreter.llm.supports_functions = False
interpreter.llm.execution_instructions = False
interpreter.computer.import_computer_api = False
interpreter.computer.offline = True
interpreter.custom_instructions = (
    "Stay offline. For medical, first aid, repair, DIY, ham radio, outdoors, "
    "or other factual questions, first run this command and use only its citations:\n"
    "nomad-search \"<the question>\"\n"
    "Do not invent sources. If the search returns nothing, say so."
)

interpreter.display_message(
    "> Model set to local Ollama `qwen3.5:9b` (offline).\n\n"
    "**Open Interpreter** will ask for approval before running any code.\n"
    "For factual questions it should run `nomad-search \"...\"` first.\n"
    "Do not use `interpreter -y` unless you intend to auto-run commands.\n"
    "Switch models with `--model ollama/llama3.1:8b` (or llama3.2:latest, gemma4:26b).\n"
    "Press `CTRL-C` to exit.\n"
)
