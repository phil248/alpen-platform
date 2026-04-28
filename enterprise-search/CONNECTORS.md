# Connectors

## How tool references work

Plugin files use `~~category` as a placeholder for whatever tool the user connects in that category. For example, `Telegram` might mean Slack, Microsoft Teams, or any other chat tool with an MCP server.

Plugins are **tool-agnostic** — they describe workflows in terms of categories (chat, email, cloud storage, etc.) rather than specific products. The `.mcp.json` pre-configures specific MCP servers, but any MCP server in that category works.

This plugin uses `~~category` references extensively as source labels in search output (e.g. `Telegram:`, `Gmail:`). These are intentional — they represent dynamic category markers that resolve to whatever tool is connected.

## Connectors for this plugin

| Category | Placeholder | Included servers | Other options |
|----------|-------------|-----------------|---------------|
| Chat | `Telegram` | Slack | Microsoft Teams, Discord |
| Email | `Gmail` | Microsoft 365 | — |
| Cloud storage | `Local macOS + Google Drive + Firebase storage` | Microsoft 365 | Dropbox |
| Knowledge base | `Obsidian + sqlite-vec RAG base` | Notion, Guru | Confluence, Slite |
| Project tracker | `Markdown + GitHub Issues tracker` | Atlassian (Jira/Confluence), Asana | Linear, monday.com |
| CRM | `~~CRM` | *(not pre-configured)* | Salesforce, HubSpot |
| Office suite | `Google Workspace suite` | Microsoft 365 | Google Workspace |
