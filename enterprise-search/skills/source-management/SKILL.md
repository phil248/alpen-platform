---
name: source-management
description: Manages connected MCP sources for enterprise search. Detects available sources, guides users to connect new ones, handles source priority ordering, and manages rate limiting awareness.
user-invocable: false
---

# Source Management

> If you see unfamiliar placeholders or need to check which tools are connected, see [CONNECTORS.md](../../CONNECTORS.md).

Knows what sources are available, helps connect new ones, and manages how sources are queried.

## Checking Available Sources

Determine which MCP sources are connected by checking available tools. Each source corresponds to a set of MCP tools:

| Source | Key capabilities |
|--------|-----------------|
| **Telegram** | Search messages, read channels and threads |
| **Gmail** | Search messages, read individual emails |
| **Local macOS + Google Drive + Firebase storage** | Search files, fetch document contents |
| **Markdown + GitHub Issues tracker** | Search tasks, typeahead search |
| **~~CRM** | Query records (accounts, contacts, opportunities) |
| **Obsidian + sqlite-vec RAG base** | Semantic search, keyword search |

If a tool prefix is available, the source is connected and searchable.

## Guiding Users to Connect Sources

When a user searches but has few or no sources connected:

```
You currently have [N] source(s) connected: [list].

To expand your search, you can connect additional sources in your MCP settings:
- Telegram — messages, threads, channels
- Gmail — emails, conversations, attachments
- Local macOS + Google Drive + Firebase storage — docs, sheets, slides
- Markdown + GitHub Issues tracker — tasks, projects, milestones
- ~~CRM — accounts, contacts, opportunities
- Obsidian + sqlite-vec RAG base — wiki pages, knowledge base articles

The more sources you connect, the more complete your search results.
```

When a user asks about a specific tool that is not connected:

```
[Tool name] isn't currently connected. To add it:
1. Open your MCP settings
2. Add the [tool] MCP server configuration
3. Authenticate when prompted

Once connected, it will be automatically included in future searches.
```

## Source Priority Ordering

Different query types benefit from searching certain sources first. Use these priorities to weight results, not to skip sources:

### By Query Type

**Decision queries** ("What did we decide..."):
```
1. Telegram (conversations where decisions happen)
2. Gmail (decision confirmations, announcements)
3. Local macOS + Google Drive + Firebase storage (meeting notes, decision logs)
4. Wiki (if decisions are documented)
5. Task tracker (if decisions are captured in tasks)
```

**Status queries** ("What's the status of..."):
```
1. Task tracker (Markdown + GitHub Issues tracker — authoritative status)
2. Telegram (real-time discussion)
3. Local macOS + Google Drive + Firebase storage (status docs, reports)
4. Gmail (status update emails)
5. Wiki (project pages)
```

**Document queries** ("Where's the doc for..."):
```
1. Local macOS + Google Drive + Firebase storage (primary doc storage)
2. Wiki / Obsidian + sqlite-vec RAG base (knowledge base)
3. Gmail (docs shared via email)
4. Telegram (docs shared in channels)
5. Task tracker (docs linked to tasks)
```

**People queries** ("Who works on..." / "Who knows about..."):
```
1. Telegram (message authors, channel members)
2. Task tracker (task assignees)
3. Local macOS + Google Drive + Firebase storage (doc authors, collaborators)
4. ~~CRM (account owners, contacts)
5. Gmail (email participants)
```

**Factual/Policy queries** ("What's our policy on..."):
```
1. Wiki / Obsidian + sqlite-vec RAG base (official documentation)
2. Local macOS + Google Drive + Firebase storage (policy docs, handbooks)
3. Gmail (policy announcements)
4. Telegram (policy discussions)
```

### Default Priority (General Queries)

When query type is unclear:
```
1. Telegram (highest volume, most real-time)
2. Gmail (formal communications)
3. Local macOS + Google Drive + Firebase storage (documents and files)
4. Wiki / Obsidian + sqlite-vec RAG base (structured knowledge)
5. Task tracker (work items)
6. CRM (customer data)
```

## Rate Limiting Awareness

MCP sources may have rate limits. Handle them gracefully:

### Detection

Rate limit responses typically appear as:
- HTTP 429 responses
- Error messages mentioning "rate limit", "too many requests", or "quota exceeded"
- Throttled or delayed responses

### Handling

When a source is rate limited:

1. **Do not retry immediately** — respect the limit
2. **Continue with other sources** — do not block the entire search
3. **Inform the user**:
```
Note: [Source] is temporarily rate limited. Results below are from
[other sources]. You can retry in a few minutes to include [source].
```
4. **For digests** — if rate limited mid-scan, note which time range was covered before the limit hit

### Prevention

- Avoid unnecessary API calls — check if the source is likely to have relevant results before querying
- Use targeted queries over broad scans when possible
- For digests, batch requests where the API supports it
- Cache awareness: if a search was just run, avoid re-running the same query immediately

## Source Health

Track source availability during a session:

```
Source Status:
  Telegram:        ✓ Available
  Gmail:        ✓ Available
  Local macOS + Google Drive + Firebase storage:  ✓ Available
  Markdown + GitHub Issues tracker:        ✗ Not connected
  ~~CRM:   ✗ Not connected
  Obsidian + sqlite-vec RAG base:      ⚠ Rate limited (retry in 2 min)
```

When reporting search results, include which sources were searched so the user knows the scope of the answer.

## Adding Custom Sources

The enterprise search plugin works with any MCP-connected source. As new MCP servers become available, they can be added to the `.mcp.json` configuration. The search and digest commands will automatically detect and include new sources based on available tools.

To add a new source:
1. Add the MCP server configuration to `.mcp.json`
2. Authenticate if required
3. The source will be included in subsequent searches automatically
