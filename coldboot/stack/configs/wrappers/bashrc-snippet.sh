# AI-AGENTS-PATH: user-space tools (uv, Open Interpreter, Goose)
if [ -f "$HOME/.local/bin/env" ]; then
  . "$HOME/.local/bin/env"
elif [ -d "$HOME/.local/bin" ]; then
  case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) PATH="$HOME/.local/bin:$PATH" ;;
  esac
fi
