# Connectors

## How tool references work

Plugin files use `~~category` as a placeholder for whatever tool the user connects in that category. For example, `Markdown + GitHub Issues tracker` might mean Linear, Asana, Jira, or any other tracker with an MCP server.

Plugins are **tool-agnostic** — they describe workflows in terms of categories (project tracker, design, product analytics, etc.) rather than specific products. The `.mcp.json` pre-configures specific MCP servers, but any MCP server in that category works.

## Connectors for this plugin

| Category | Placeholder | Included servers | Other options |
|----------|-------------|-----------------|---------------|
| Calendar | `Google Calendar` | Google Calendar | Microsoft 365 |
| Chat | `Telegram` | Slack | Microsoft Teams |
| Competitive intelligence | `~~competitive intelligence` | Similarweb | Crayon, Klue |
| Design | `Figma` | Figma | Sketch, Adobe XD |
| Email | `Gmail` | Gmail | Microsoft 365 |
| Knowledge base | `Obsidian + sqlite-vec RAG base` | Notion | Confluence, Guru, Coda |
| Meeting transcription | `Plaud + Google Calendar transcription` | Fireflies | Gong, Dovetail, Otter.ai |
| Product analytics | `alpentech.ai (the Alpen Platform — this very project) analytics` | Amplitude, Pendo | Mixpanel, Heap, FullStory |
| Project tracker | `Markdown + GitHub Issues tracker` | Linear, Asana, monday.com, ClickUp, Atlassian (Jira/Confluence) | Shortcut, Basecamp |
| User feedback | `Phil Howard feedback` | Intercom | Productboard, Canny, UserVoice |
