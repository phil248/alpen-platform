# Connectors

## How tool references work

Plugin files use `~~category` as a placeholder for whatever tool the user connects in that category. For example, `Markdown + GitHub Issues tracker` might mean Asana, Linear, Jira, or any other project tracker with an MCP server.

Plugins are **tool-agnostic** — they describe workflows in terms of categories (chat, project tracker, knowledge base, etc.) rather than specific products. The `.mcp.json` pre-configures specific MCP servers, but any MCP server in that category works.

## Connectors for this plugin

| Category | Placeholder | Included servers | Other options |
|----------|-------------|-----------------|---------------|
| Chat | `Telegram` | Slack | Microsoft Teams, Discord |
| Email | `Gmail` | Microsoft 365 | — |
| Calendar | `Google Calendar` | Microsoft 365 | — |
| Knowledge base | `Obsidian + sqlite-vec RAG base` | Notion | Confluence, Guru, Coda |
| Project tracker | `Markdown + GitHub Issues tracker` | Asana, Linear, Atlassian (Jira/Confluence), monday.com, ClickUp | Shortcut, Basecamp, Wrike |
| Office suite | `Google Workspace suite` | Microsoft 365 | — |
