# llm-tools-fabric

Fabric pattern integration for [llm](https://github.com/simonw/llm) - run 230+ AI patterns as isolated subagents.

## Installation

```bash
llm install git+https://github.com/c0ffee0wl/llm-tools-fabric
```

## Usage

The `fabric` tool can be used standalone with llm CLI or integrated with llm-sidechat.

### Standalone CLI

```bash
# With explicit pattern
llm --tool fabric -f yt:https://youtube.com/watch?v=VIDEO_ID \
    '{"task": "", "pattern": "extract_wisdom", "input_text": ""}'

# With auto-selection (pattern inferred from task)
llm --tool fabric -f yt:https://youtube.com/watch?v=VIDEO_ID \
    '{"task": "summarize this YouTube video", "input_text": ""}'

# Get pattern suggestions
llm --tool fabric '{"task": "analyze this document", "input_text": "..."}'
```

### In llm-sidechat

The AI assistant can automatically use the fabric tool:

```
you> summarize this YouTube video: https://youtube.com/watch?v=VIDEO_ID

[AI loads transcript via load_yt, then calls fabric with auto-selected pattern]
```

## How It Works

1. **Auto-Selection**: When you describe a task (e.g., "summarize video", "analyze threat report"), the tool automatically selects an appropriate Fabric pattern.

2. **Explicit Pattern**: You can specify a pattern name directly for precise control.

3. **Suggestions**: For ambiguous requests, the tool uses `fabric:suggest_pattern` to recommend appropriate patterns.

4. **Isolation**: Patterns run via `model.prompt()` - isolated from the main conversation context.

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
