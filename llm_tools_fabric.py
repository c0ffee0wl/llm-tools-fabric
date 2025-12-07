"""
LLM tools for Fabric pattern integration.

Provides the `fabric` tool for executing Fabric AI patterns as isolated subagents.
Supports auto-selection of patterns based on task description, or explicit pattern
specification. Works standalone with llm CLI or integrated with llm-sidechat.

Fabric patterns are specialized AI prompts from https://github.com/danielmiessler/fabric
"""
import json
import os
import re
import tempfile
import urllib.request
from typing import Optional, Tuple

import llm


# Pattern auto-selection rules: (keywords, content_hints, pattern_name)
# Keywords are checked against task description (case-insensitive)
# Content hints are checked against input_text (optional additional signal)
# Supports both English and German keywords
AUTO_SELECT_RULES = [
    # YouTube-specific patterns (EN + DE)
    (["youtube", "video", "summarize"], ["youtube.com", "youtu.be"], "youtube_summary"),
    (["youtube", "video", "zusammenfass"], ["youtube.com", "youtu.be"], "youtube_summary"),  # DE
    (["wisdom", "insights", "extract"], ["youtube.com", "youtu.be"], "extract_wisdom"),
    (["weisheit", "erkenntnisse", "extrahier"], ["youtube.com", "youtu.be"], "extract_wisdom"),  # DE
    (["lecture", "class", "lesson"], ["youtube.com", "youtu.be"], "summarize_lecture"),
    (["vorlesung", "vortrag", "lektion"], ["youtube.com", "youtu.be"], "summarize_lecture"),  # DE
    (["chapters", "timestamps", "sections"], ["youtube.com", "youtu.be"], "create_video_chapters"),
    (["kapitel", "zeitstempel", "abschnitte"], ["youtube.com", "youtu.be"], "create_video_chapters"),  # DE

    # PDF/Document patterns (EN + DE)
    (["paper", "academic", "research"], [], "summarize_paper"),
    (["paper", "akademisch", "forschung", "wissenschaftlich"], [], "summarize_paper"),  # DE
    (["analyze", "paper"], [], "analyze_paper"),
    (["analysier", "paper"], [], "analyze_paper"),  # DE

    # Security/Threat patterns (EN + DE)
    (["threat", "report", "security"], [], "analyze_threat_report"),
    (["bedrohung", "bericht", "sicherheit"], [], "analyze_threat_report"),  # DE
    (["malware", "ioc", "indicator"], [], "analyze_malware"),
    (["schadsoftware", "indikator"], [], "analyze_malware"),  # DE
    (["sigma", "detection", "rule"], [], "create_sigma_rules"),
    (["sigma", "erkennung", "regel"], [], "create_sigma_rules"),  # DE
    (["stride", "threat", "model"], [], "create_stride_threat_model"),
    (["stride", "bedrohungsmodell"], [], "create_stride_threat_model"),  # DE

    # Code patterns (EN + DE)
    (["explain", "code"], [], "explain_code"),
    (["erklär", "code"], [], "explain_code"),  # DE
    (["review", "design", "architecture"], [], "review_design"),
    (["überprüf", "design", "architektur"], [], "review_design"),  # DE

    # General patterns (EN + DE)
    (["extract", "ideas"], [], "extract_ideas"),
    (["extrahier", "ideen"], [], "extract_ideas"),  # DE
    (["extract", "insights"], [], "extract_insights"),
    (["extrahier", "erkenntnisse"], [], "extract_insights"),  # DE
    (["analyze", "claims", "truth"], [], "analyze_claims"),
    (["analysier", "behauptungen", "wahrheit"], [], "analyze_claims"),  # DE
    (["summarize"], [], "summarize"),
    (["zusammenfass"], [], "summarize"),  # DE
]


# Source-based pattern selection: (action_keyword, pattern_name)
# When source prefix provides explicit context, only the action keyword is needed
SOURCE_ACTIONS = {
    'yt': [
        ('summarize', 'youtube_summary'),
        ('zusammenfass', 'youtube_summary'),
        ('wisdom', 'extract_wisdom'),
        ('extract', 'extract_wisdom'),
        ('insights', 'extract_wisdom'),
        ('lecture', 'summarize_lecture'),
        ('chapters', 'create_video_chapters'),
    ],
    'pdf': [
        ('summarize', 'summarize_paper'),
        ('analyze', 'analyze_paper'),
    ],
}


def _download_url_to_temp(url: str, suffix: str = '') -> str:
    """Download URL to a temporary file, return the path."""
    request = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
        }
    )
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        with urllib.request.urlopen(request) as response:
            tmp.write(response.read())
        return tmp.name


def _load_source(source: str) -> str:
    """
    Load content from a source URI.

    Supported prefixes:
    - file:/path/to/doc.md - Local text file (markdown, txt, etc.)
    - yt:VIDEO_URL - YouTube transcript
    - pdf:FILE_PATH or pdf:URL - PDF document
    - github:owner/repo - GitHub repository
    - url:https://... - Web page
    """
    if ':' not in source:
        raise ValueError(f"Invalid source format: {source}. Expected prefix:argument (e.g., yt:VIDEO_ID, pdf:/path/to/file)")

    prefix, argument = source.split(':', 1)
    prefix = prefix.lower()

    if prefix == 'file':
        # Local text file (markdown, txt, etc.)
        path = os.path.expanduser(argument)
        if not os.path.exists(path):
            raise ValueError(f"File not found: {path}")
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()

    elif prefix == 'yt':
        loaders = llm.get_fragment_loaders()
        if 'yt' not in loaders:
            raise ValueError("YouTube loader not available (install llm-fragments-youtube-transcript)")
        results = loaders['yt'](argument)
        return '\n\n'.join(str(r) for r in results)

    elif prefix == 'pdf':
        loaders = llm.get_fragment_loaders()
        if 'pdf' not in loaders:
            raise ValueError("PDF loader not available")
        # Handle remote PDFs
        if argument.startswith(('http://', 'https://')):
            temp_file = _download_url_to_temp(argument, suffix='.pdf')
            try:
                results = loaders['pdf'](temp_file)
            finally:
                os.unlink(temp_file)
        else:
            path = os.path.expanduser(argument)
            results = loaders['pdf'](path)
        return '\n\n'.join(str(r) for r in results)

    elif prefix == 'github':
        loaders = llm.get_fragment_loaders()
        if 'github' not in loaders:
            raise ValueError("GitHub loader not available")
        results = loaders['github'](argument)
        return '\n\n'.join(str(r) for r in results)

    elif prefix == 'url':
        # Use trafilatura for web pages with custom user agent
        import trafilatura
        from trafilatura.settings import use_config
        config = use_config()
        config.set("DEFAULT", "USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
        downloaded = trafilatura.fetch_url(argument, config=config)
        if downloaded is None:
            raise ValueError(f"Failed to fetch URL: {argument}")
        content = trafilatura.extract(downloaded, output_format="markdown")
        return content or ""

    else:
        raise ValueError(f"Unknown source prefix: {prefix}. Supported: file, yt, pdf, github, url")


def _auto_select_pattern(task: str, input_text: str = "", source: str = "") -> Optional[str]:
    """
    Auto-select a Fabric pattern based on task description and input content.

    Returns pattern name if a clear match is found, None otherwise.
    """
    task_lower = task.lower()

    # Source-based: direct action lookup (skip complex keyword matching)
    if ':' in source:
        prefix = source.split(':', 1)[0].lower()
        if prefix in SOURCE_ACTIONS:
            for action, pattern in SOURCE_ACTIONS[prefix]:
                if action in task_lower:
                    return pattern

    # No source or unknown prefix: use keyword + content hint matching
    input_lower = input_text.lower()[:1000]  # Only check first 1000 chars for hints

    for keywords, content_hints, pattern_name in AUTO_SELECT_RULES:
        # Check if all keywords are present in task
        if all(kw in task_lower for kw in keywords):
            # If content hints specified, check if any are present
            if content_hints:
                if any(hint in input_lower for hint in content_hints):
                    return pattern_name
            else:
                return pattern_name

    return None


def _suggest_patterns(task: str) -> str:
    """
    Get pattern suggestions using fabric:suggest_pattern template.

    Returns the suggestion text from the template.
    """
    try:
        from llm.cli import load_template  # Deferred import to avoid circular import
        template = load_template("fabric:suggest_pattern")
        model = llm.get_model(llm.get_default_model())

        # Build prompt with task description
        prompt = f"User request: {task}"
        system = template.system or ""

        response = model.prompt(prompt, system=system)
        return response.text()
    except Exception as e:
        return f"Error getting suggestions: {e}"


def _run_pattern(pattern_name: str, input_text: str) -> str:
    """
    Execute a Fabric pattern in isolation using direct model.prompt().

    This ensures the pattern execution doesn't pollute the main conversation context.
    """
    try:
        # Deferred import to avoid circular import
        from llm.cli import load_template
        template = load_template(f"fabric:{pattern_name}")
    except Exception as e:
        raise ValueError(f"Pattern '{pattern_name}' not found: {e}")

    # Get current default model
    model = llm.get_model(llm.get_default_model())

    # Direct prompt - NOT in a conversation = isolated from main context
    system = template.system or ""
    response = model.prompt(input_text, system=system)

    return response.text()


def fabric(task: str, pattern: str = "", input_text: str = "", source: str = "") -> str:
    """
    Execute a Fabric AI pattern as an isolated subagent.

    Use this tool when you need to run Fabric patterns for tasks like:
    summarization, content extraction, security analysis, code review, etc.
    Fabric patterns run in isolation - large inputs stay out of main context.

    IMPORTANT: When processing YouTube videos, PDFs, web pages, or local files,
    use the 'source' parameter instead of loading content first. This keeps
    the full content out of the main conversation context.

    Args:
        task: Description of what to accomplish. Used for auto-selecting
              the appropriate Fabric pattern.
        pattern: (Optional) Specific Fabric pattern name to run. If not provided,
                 auto-selects based on task or suggests options.
        input_text: Content to process (use 'source' parameter instead when possible).
        source: (Optional) Content source URI. Loads content internally
                (keeps it out of main context). Formats:
                - file:/path/to/doc.md - Local text file (markdown, txt, etc.)
                - yt:VIDEO_URL - YouTube transcript
                - pdf:FILE_PATH or pdf:URL - PDF document
                - github:owner/repo - GitHub repository
                - url:https://... - Web page

    Returns:
        JSON with the processed result from the Fabric pattern, or pattern
        suggestions if no clear pattern match is found.

    Examples:
        # YouTube video (content stays in subagent)
        fabric(task="summarize video", source="yt:dQw4w9WgXcQ")

        # Local document
        fabric(task="extract insights", source="file:~/notes.md")

        # With explicit pattern
        fabric(pattern="extract_wisdom", source="yt:VIDEO_ID")

        # With pre-loaded content (less efficient for main context)
        fabric(task="summarize", input_text=already_loaded_content)
    """
    # Load from source if provided (keeps content in isolated context)
    if source:
        try:
            input_text = _load_source(source)
        except Exception as e:
            return json.dumps({
                "error": f"Failed to load source: {e}",
                "source": source
            }, indent=2)

    # Validate input
    if not task and not pattern:
        return json.dumps({
            "error": "Either 'task' or 'pattern' must be provided",
            "hint": "Describe what you want to do, or specify a pattern name"
        }, indent=2)

    # If explicit pattern provided, run it directly
    if pattern:
        pattern_name = pattern.strip()
        # Remove fabric: prefix if accidentally included
        if pattern_name.startswith("fabric:"):
            pattern_name = pattern_name[7:]

        try:
            result = _run_pattern(pattern_name, input_text)
            return json.dumps({
                "pattern": pattern_name,
                "result": result
            }, indent=2)
        except ValueError as e:
            return json.dumps({
                "error": str(e),
                "hint": "Use fabric(task='describe what you want') to get pattern suggestions"
            }, indent=2)
        except Exception as e:
            return json.dumps({
                "error": f"Pattern execution failed: {e}",
                "pattern": pattern_name
            }, indent=2)

    # Try auto-selection based on task
    selected_pattern = _auto_select_pattern(task, input_text, source)

    if selected_pattern:
        # Auto-selected a pattern, run it
        try:
            result = _run_pattern(selected_pattern, input_text)
            return json.dumps({
                "pattern": selected_pattern,
                "auto_selected": True,
                "result": result
            }, indent=2)
        except Exception as e:
            return json.dumps({
                "error": f"Pattern execution failed: {e}",
                "pattern": selected_pattern,
                "auto_selected": True
            }, indent=2)

    # No clear match - get suggestions
    suggestions = _suggest_patterns(task)
    return json.dumps({
        "task": task,
        "suggestions": suggestions,
        "hint": "Call fabric(pattern='pattern_name', input_text=content) with your chosen pattern"
    }, indent=2)


@llm.hookimpl
def register_tools(register):
    """Register the fabric tool with llm."""
    register(fabric)
