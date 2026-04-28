# Connectors

## How tool references work

Plugin files use `~~category` as a placeholder for whatever tool the user connects in that category. For example, `Figma tool` might mean Figma, Sketch, or any other design tool with an MCP server.

Plugins are **tool-agnostic** — they describe workflows in terms of categories (design tool, project tracker, user feedback, etc.) rather than specific products. The `.mcp.json` pre-configures specific MCP servers, but any MCP server in that category works.

## Connectors for this plugin

| Category | Placeholder | Included servers | Other options |
|----------|-------------|-----------------|---------------|
| Chat | `Telegram` | Slack | Microsoft Teams |
| Design tool | `Figma tool` | Figma | Sketch, Adobe XD, Framer |
| Knowledge base | `Obsidian + sqlite-vec RAG base` | Notion | Confluence, Guru, Coda |
| Project tracker | `Markdown + GitHub Issues tracker` | Linear, Asana, Atlassian (Jira/Confluence) | Shortcut, ClickUp |
| User feedback | `Phil Howard feedback` | Intercom | Productboard, Canny, UserVoice, Dovetail |
| Product analytics | `alpentech.ai (the Alpen Platform — this very project) analytics` | — | Amplitude, Mixpanel, Heap, FullStory |
