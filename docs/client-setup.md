# MCP Client Setup

This guide shows how to add `better-blender-mcp` to:
- Claude Desktop
- VS Code (GitHub Copilot Agent mode)
- VS Code (Continue extension)
- Codex

## Prerequisites

1. Install this project and CLI:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

2. Install and enable the Blender add-on, then click **Start Bridge** in Blender.

3. Use the same token in both places:
- Blender add-on preference: token value
- Client MCP config: `BETTER_BLENDER_TOKEN`

## Shared MCP Server Values

Use these values in each client config:

- `command`: `better-blender-mcp` (or absolute path to the binary in `.venv/bin/`)
- `args`: `["serve"]`
- `env.BETTER_BLENDER_HOST`: `"127.0.0.1"`
- `env.BETTER_BLENDER_PORT`: `"8765"`
- `env.BETTER_BLENDER_TOKEN`: `"change-me"` (replace with your real token)

You can generate a base JSON snippet with:

```bash
better-blender-mcp print-config --client generic
```

## Claude Desktop

Add the server to Claude Desktop's `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "better-blender": {
      "type": "stdio",
      "command": "better-blender-mcp",
      "args": ["serve"],
      "env": {
        "BETTER_BLENDER_HOST": "127.0.0.1",
        "BETTER_BLENDER_PORT": "8765",
        "BETTER_BLENDER_TOKEN": "change-me"
      }
    }
  }
}
```

Notes:
- If `better-blender-mcp` is not on `PATH`, use an absolute command path.
- Remote MCP connectors in Claude Desktop should be added via **Settings > Connectors**.

## VS Code (GitHub Copilot Agent Mode)

Create `.vscode/mcp.json` in your workspace:

```json
{
  "servers": {
    "better-blender": {
      "type": "stdio",
      "command": "better-blender-mcp",
      "args": ["serve"],
      "env": {
        "BETTER_BLENDER_HOST": "127.0.0.1",
        "BETTER_BLENDER_PORT": "8765",
        "BETTER_BLENDER_TOKEN": "change-me"
      }
    }
  }
}
```

Then:
1. Start/trust the MCP server from the `mcp.json` code lens or `MCP: List Servers`.
2. Open Copilot Chat and switch to **Agent** mode.
3. Enable the `better-blender` tools in the tools picker.

## VS Code (Continue Extension)

Create `.continue/mcpServers/better-blender.yaml` in your workspace:

```yaml
name: Better Blender MCP
version: 0.0.1
schema: v1
mcpServers:
  - name: better-blender
    type: stdio
    command: better-blender-mcp
    args:
      - serve
    env:
      BETTER_BLENDER_HOST: "127.0.0.1"
      BETTER_BLENDER_PORT: "8765"
      BETTER_BLENDER_TOKEN: "change-me"
```

Then:
1. Restart/reload Continue if needed.
2. Switch Continue to **Agent** mode (MCP tools are agent-only).
3. Ask it to call a tool, for example: `Run get_blender_status`.

## Codex

Add this to `~/.codex/config.toml`:

```toml
[mcp_servers.better-blender]
command = "better-blender-mcp"
args = ["serve"]

[mcp_servers.better-blender.env]
BETTER_BLENDER_HOST = "127.0.0.1"
BETTER_BLENDER_PORT = "8765"
BETTER_BLENDER_TOKEN = "change-me"
```

Notes:
- Codex CLI and the Codex IDE extension share `~/.codex/config.toml`.
- If needed, set an absolute command path (for example, your project `.venv/bin/better-blender-mcp`).

## References

- Anthropic Claude Code MCP docs: https://docs.anthropic.com/en/docs/claude-code/mcp
- Claude Desktop local MCP help: https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop
- VS Code MCP setup: https://code.visualstudio.com/docs/copilot/customization/mcp-servers
- VS Code MCP config reference: https://code.visualstudio.com/docs/copilot/reference/mcp-configuration
- GitHub Copilot MCP overview: https://docs.github.com/en/copilot/how-tos/provide-context/use-mcp
- Continue MCP deep dive: https://docs.continue.dev/customize/deep-dives/mcp
- Continue config reference: https://docs.continue.dev/reference
- OpenAI Docs MCP / Codex MCP config: https://platform.openai.com/docs/docs-mcp
