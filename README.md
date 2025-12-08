# llm-tools-fabric

Fabric pattern integration for [llm](https://github.com/simonw/llm) - run 230+ AI patterns as isolated subagents.

## Installation

```bash
llm install git+https://github.com/c0ffee0wl/llm-tools-fabric
```

## Usage

The `prompt_fabric` tool can be used standalone with llm CLI or integrated with llm-sidechat.

### Standalone CLI

```bash
# YouTube video with auto-selected pattern
llm --tool prompt_fabric '{"task": "summarize", "source": "yt:dQw4w9WgXcQ"}'

# YouTube video with explicit pattern
llm --tool prompt_fabric '{"pattern": "extract_wisdom", "source": "yt:youtube.com/watch?v=VIDEO_ID"}'

# PDF analysis
llm --tool prompt_fabric '{"task": "summarize", "source": "pdf:~/paper.pdf"}'

# Web page
llm --tool prompt_fabric '{"task": "summarize", "source": "url:example.com/article"}'

# GitHub repository
llm --tool prompt_fabric '{"task": "analyze", "source": "github:anthropics/anthropic-sdk-python"}'

# Pre-loaded content
llm --tool prompt_fabric '{"task": "explain code", "input_text": "def hello(): print(world)"}'
```

### In llm-sidechat

The AI assistant can automatically use the prompt_fabric tool:

```
you> use fabric to summarize this YouTube video: https://youtube.com/watch?v=VIDEO_ID

[AI calls prompt_fabric with source parameter, returns structured result]
```

## Output Format

Output uses XML-style tags to preserve Markdown formatting:

**Success:**
```xml
<fabric_result pattern="extract_wisdom" auto_selected="true">
# Key Insights

1. First insight from the content
2. Second insight
3. Third insight
</fabric_result>
```

**Error:**
```xml
<fabric_error source="yt:invalid_id">
Failed to load source: video not found
</fabric_error>
```

**Suggestions** (when no pattern matches):
```xml
<fabric_suggestions task="analyze document">
Recommended patterns:
- summarize_paper for academic documents
- analyze_claims for fact-checking

Hint: Call prompt_fabric(pattern='pattern_name', input_text=content) with your chosen pattern.
</fabric_suggestions>
```

## Source Formats

| Prefix | Description | Example |
|--------|-------------|---------|
| `yt:` | YouTube video (ID or URL) | `yt:dQw4w9WgXcQ`, `yt:youtube.com/watch?v=...` |
| `pdf:` | PDF document (local or URL) | `pdf:~/paper.pdf`, `pdf:example.com/doc.pdf` |
| `url:` | Web page | `url:example.com/article` |
| `github:` | GitHub repository | `github:owner/repo`, `github:https://github.com/owner/repo` |
| `file:` | Local text file | `file:~/notes.md` |

## How It Works

1. **Auto-Selection**: When you describe a task (e.g., "summarize", "extract wisdom"), the tool automatically selects an appropriate Fabric pattern based on task keywords and source type.

2. **Explicit Pattern**: You can specify a pattern name directly for precise control.

3. **Suggestions**: For ambiguous requests, the tool uses `fabric:suggest_pattern` to recommend appropriate patterns.

4. **Isolation**: Patterns run via `model.prompt()` - isolated from the main conversation context. Large content stays out of the chat history.

## Auto-Selected Patterns

| Task Keywords | Pattern |
|--------------|---------|
| summarize + video/youtube | `youtube_summary` |
| extract + wisdom/insights | `extract_wisdom` |
| lecture/class | `summarize_lecture` |
| chapters/timestamps | `create_video_chapters` |
| paper/academic | `summarize_paper` |
| threat + report | `analyze_threat_report` |
| malware/ioc | `analyze_malware` |
| sigma/detection | `create_sigma_rules` |
| explain + code | `explain_code` |
| review/design | `review_design` |
| extract + ideas | `extract_ideas` |
| analyze + claims | `analyze_claims` |
| summarize | `summarize` |

## All Fabric Patterns

This plugin works with all 230+ patterns from [danielmiessler/fabric](https://github.com/danielmiessler/Fabric). Common patterns include:

- **Analysis**: `analyze_claims`, `analyze_paper`, `analyze_threat_report`, `analyze_malware`
- **Extraction**: `extract_wisdom`, `extract_ideas`, `extract_insights`, `extract_article_wisdom`
- **Summarization**: `summarize`, `summarize_paper`, `summarize_lecture`, `youtube_summary`
- **Creation**: `create_sigma_rules`, `create_stride_threat_model`, `create_video_chapters`
- **Code**: `explain_code`, `review_design`, `create_coding_project`

## Dependencies

- [llm](https://github.com/simonw/llm) - LLM CLI tool
- [llm-templates-fabric](https://github.com/Damon-McMinn/llm-templates-fabric) - Fabric template loader

## License

Apache-2.0
