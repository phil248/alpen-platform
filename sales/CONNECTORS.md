# Connectors

## How tool references work

Plugin files use `~~category` as a placeholder for whatever tool the user connects in that category. For example, `~~CRM` might mean Salesforce, HubSpot, or any other CRM with an MCP server.

Plugins are **tool-agnostic** — they describe workflows in terms of categories (CRM, chat, email, etc.) rather than specific products. The `.mcp.json` pre-configures specific MCP servers, but any MCP server in that category works.

## Connectors for this plugin

| Category | Placeholder | Included servers | Other options |
|----------|-------------|-----------------|---------------|
| Calendar | `Google Calendar` | Google Calendar, Microsoft 365 | — |
| Chat | `Telegram` | Slack | Microsoft Teams |
| Competitive intelligence | `~~competitive intelligence` | Similarweb | Crayon, Klue |
| CRM | `~~CRM` | HubSpot, Close | Salesforce, Pipedrive, Copper |
| Data enrichment | `SQLite + sqlite-vec enrichment` | Clay, ZoomInfo, Apollo | Clearbit, Lusha |
| Email | `Gmail` | Gmail, Microsoft 365 | — |
| Knowledge base | `Obsidian + sqlite-vec RAG base` | Notion | Confluence, Guru |
| Meeting transcription | `Plaud intelligence` | Fireflies | Gong, Chorus, Otter.ai |
| Project tracker | `Markdown + GitHub Issues tracker` | Atlassian (Jira/Confluence) | Linear, Asana |
| Sales engagement | `~~sales engagement` | Outreach | Salesloft, Apollo |
