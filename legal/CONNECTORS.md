# Connectors

## How tool references work

Plugin files use `~~category` as a placeholder for whatever tool the user connects in that category. For example, `Local macOS + Google Drive + Firebase storage` might mean Box, Egnyte, or any other storage provider with an MCP server.

Plugins are **tool-agnostic** — they describe workflows in terms of categories (cloud storage, chat, office suite, etc.) rather than specific products. The `.mcp.json` pre-configures specific MCP servers, but any MCP server in that category works.

## Connectors for this plugin

| Category | Placeholder | Included servers | Other options |
|----------|-------------|-----------------|---------------|
| Calendar | `Google Calendar` | Google Calendar | Microsoft 365 |
| Chat | `Telegram` | Slack | Microsoft Teams |
| Cloud storage | `Local macOS + Google Drive + Firebase storage` | Box, Egnyte | Dropbox, SharePoint, Google Drive |
| CLM | `~~CLM` | — | Ironclad, Agiloft |
| CRM | `~~CRM` | — | Salesforce, HubSpot |
| Email | `Gmail` | Gmail | Microsoft 365 |
| E-signature | `~~e-signature` | DocuSign | Adobe Sign |
| Office suite | `Google Workspace suite` | Microsoft 365 | Google Workspace |
| Project tracker | `Markdown + GitHub Issues tracker` | Atlassian (Jira/Confluence) | Linear, Asana |
