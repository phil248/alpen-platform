# Connectors

## How tool references work

Plugin files use `~~category` as a placeholder for whatever tool the user connects in that category. For example, `~~support platform` might mean Intercom, Zendesk, or any other support tool with an MCP server.

Plugins are **tool-agnostic** — they describe workflows in terms of categories (support platform, CRM, chat, etc.) rather than specific products. The `.mcp.json` pre-configures specific MCP servers, but any MCP server in that category works.

## Connectors for this plugin

| Category | Placeholder | Included servers | Other options |
|----------|-------------|-----------------|---------------|
| Chat | `Telegram` | Slack | Microsoft Teams |
| Email | `Gmail` | Microsoft 365 | — |
| Cloud storage | `Local macOS + Google Drive + Firebase storage` | Microsoft 365 | — |
| Support platform | `~~support platform` | Intercom | Zendesk, Freshdesk, HubSpot Service Hub |
| CRM | `~~CRM` | HubSpot | Salesforce, Pipedrive |
| Knowledge base | `Obsidian + sqlite-vec RAG base` | Guru, Notion | Confluence, Help Scout |
| Project tracker | `Markdown + GitHub Issues tracker` | Atlassian (Jira/Confluence) | Linear, Asana |
