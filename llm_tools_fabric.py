"""
LLM tools for Fabric pattern integration.

Provides the `prompt_fabric` tool for executing Fabric AI patterns as isolated subagents.
Supports auto-selection of patterns based on task description, or explicit pattern
specification. Works standalone with llm CLI or integrated with llm-sidechat.

Fabric patterns are specialized AI prompts from https://github.com/danielmiessler/fabric
"""
import os
import re
import tempfile
import urllib.request
from typing import Optional

import llm


def _escape_xml_attr(value: str) -> str:
    """Escape special characters for use in XML attribute values."""
    return (value
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


# Pattern auto-selection rules: (keywords, content_hints, pattern_name)
# Keywords are checked against task description (case-insensitive)
# Content hints are checked against input_text (optional additional signal)
AUTO_SELECT_RULES = [
    # YouTube-specific patterns
    (["youtube", "video", "summarize"], ["youtube.com", "youtu.be"], "youtube_summary"),
    (["wisdom", "insights", "extract"], ["youtube.com", "youtu.be"], "extract_wisdom"),
    (["lecture", "class", "lesson"], ["youtube.com", "youtu.be"], "summarize_lecture"),
    (["chapters", "timestamps", "sections"], ["youtube.com", "youtu.be"], "create_video_chapters"),

    # PDF/Document patterns
    (["paper", "academic", "research"], [], "summarize_paper"),
    (["analyze", "paper"], [], "analyze_paper"),

    # Security/Threat patterns
    (["threat", "report"], [], "analyze_threat_report"),
    (["malware", "ioc", "indicator"], [], "analyze_malware"),
    (["sigma", "detection", "rule"], [], "create_sigma_rules"),
    (["stride", "threat", "model"], [], "create_stride_threat_model"),

    # Code patterns
    (["explain", "code"], [], "explain_code"),
    (["review", "design", "architecture"], [], "review_design"),

    # General patterns
    (["extract", "ideas"], [], "extract_ideas"),
    (["extract", "insights"], [], "extract_insights"),
    (["analyze", "claims", "truth"], [], "analyze_claims"),
    (["summarize"], [], "summarize"),
]


# Source-based pattern selection: (action_keyword, pattern_name)
# When source prefix provides explicit context, only the action keyword is needed
# Last entry with empty string is the default if no keywords match
SOURCE_ACTIONS = {
    'yt': [
        ('summarize', 'youtube_summary'),
        ('wisdom', 'extract_wisdom'),
        ('extract', 'extract_wisdom'),
        ('insights', 'extract_wisdom'),
        ('lecture', 'summarize_lecture'),
        ('chapters', 'create_video_chapters'),
        ('', 'youtube_summary'),  # default for YouTube
    ],
    'pdf': [
        ('summarize', 'summarize_paper'),
        ('analyze', 'analyze_paper'),
        ('', 'summarize_paper'),  # default for PDF
    ],
}


def _normalize_url(argument: str) -> str:
    """
    Normalize a URL by adding https:// if no protocol is present.

    Args:
        argument: URL string, possibly without protocol

    Returns:
        URL with protocol (https:// added if missing)
    """
    argument = argument.strip()
    if argument.startswith(('http://', 'https://')):
        return argument
    return f"https://{argument}"


def _normalize_github_repo(argument: str) -> str:
    """
    Normalize GitHub repository reference to owner/repo format.

    Handles:
    - owner/repo (pass through)
    - https://github.com/owner/repo
    - github.com/owner/repo
    - https://github.com/owner/repo/tree/branch/path

    Returns owner/repo format or raises ValueError if invalid.
    """
    argument = argument.strip()

    # Handle full GitHub URLs
    if 'github.com' in argument:
        # Remove protocol if present
        url = argument
        if url.startswith(('http://', 'https://')):
            url = url.split('://', 1)[1]

        # Remove github.com/
        if url.startswith('github.com/'):
            url = url[11:]  # len('github.com/')

        # Extract owner/repo (first two path segments)
        parts = url.split('/')
        if len(parts) >= 2:
            owner, repo = parts[0], parts[1]
            # Remove .git suffix if present
            if repo.endswith('.git'):
                repo = repo[:-4]
            return f"{owner}/{repo}"

    # Check if it's already in owner/repo format
    if '/' in argument and not argument.startswith('/'):
        parts = argument.split('/')
        if len(parts) >= 2 and parts[0] and parts[1]:
            # Basic validation: owner and repo should be non-empty
            owner, repo = parts[0], parts[1].split('.git')[0]
            return f"{owner}/{repo}"

    raise ValueError(
        f"Invalid GitHub reference: '{argument}'. "
        "Expected 'owner/repo' or a GitHub URL (e.g., 'https://github.com/owner/repo')"
    )


def _normalize_youtube_url(argument: str) -> str:
    """
    Normalize YouTube input to a full URL that the transcript loader can handle.

    Handles:
    - Raw video IDs: H17rN9Cz47w
    - Full URLs: https://www.youtube.com/watch?v=...
    - URLs without protocol: youtube.com/watch?v=..., youtu.be/...
    - Various YouTube URL formats: /watch, /embed/, /shorts/, youtu.be

    Returns a normalized URL or raises ValueError if invalid.
    """
    argument = argument.strip()

    # Already has protocol - pass through
    if argument.startswith(('http://', 'https://')):
        return argument

    # Check if it looks like a URL without protocol
    youtube_domains = ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be')
    for domain in youtube_domains:
        if argument.startswith(domain):
            return f"https://{argument}"

    # Assume it's a video ID - validate format
    # YouTube video IDs are 11 characters, alphanumeric with - and _
    if re.match(r'^[a-zA-Z0-9_-]{10,12}$', argument):
        return f"https://www.youtube.com/watch?v={argument}"

    # Doesn't look like a valid video ID or URL
    raise ValueError(
        f"Invalid YouTube reference: '{argument}'. "
        "Expected a video ID (e.g., 'dQw4w9WgXcQ') or URL (e.g., 'https://youtube.com/watch?v=...')"
    )


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
    - yt:VIDEO_ID or yt:URL - YouTube transcript (protocol optional)
    - pdf:FILE_PATH or pdf:URL - PDF document (protocol optional for URLs)
    - github:owner/repo or github:URL - GitHub repository (full URLs supported)
    - url:ADDRESS - Web page (protocol optional, https:// added if missing)
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
        # Normalize to full URL - handles video IDs, URLs without protocol, etc.
        url = _normalize_youtube_url(argument)
        results = loaders['yt'](url)
        return '\n\n'.join(str(r) for r in results)

    elif prefix == 'pdf':
        loaders = llm.get_fragment_loaders()
        if 'pdf' not in loaders:
            raise ValueError("PDF loader not available")
        # Determine if argument is a URL or local file path
        argument = argument.strip()
        if argument.startswith(('http://', 'https://')):
            # Explicit URL protocol
            is_url = True
        elif argument.startswith(('/', './', '../', '~')):
            # Explicit path indicators - definitely a file
            is_url = False
        elif os.path.exists(os.path.expanduser(argument)):
            # File exists locally
            is_url = False
        elif '/' not in argument:
            # Just a filename with no path (e.g., "paper.pdf") - treat as file
            is_url = False
        else:
            # Has path structure - check if first segment looks like a domain
            # e.g., "example.com/doc.pdf" vs "docs/paper.pdf"
            first_segment = argument.split('/')[0]
            is_url = '.' in first_segment and len(first_segment.split('.')[0]) > 0
        if is_url:
            url = _normalize_url(argument)
            temp_file = _download_url_to_temp(url, suffix='.pdf')
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
        # Normalize to owner/repo format - handles full GitHub URLs
        repo = _normalize_github_repo(argument)
        results = loaders['github'](repo)
        return '\n\n'.join(str(r) for r in results)

    elif prefix == 'url':
        # Use trafilatura for web pages with custom user agent
        import trafilatura
        from trafilatura.settings import use_config
        # Normalize URL - add https:// if missing
        url = _normalize_url(argument)
        config = use_config()
        config.set("DEFAULT", "USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
        downloaded = trafilatura.fetch_url(url, config=config)
        if downloaded is None:
            raise ValueError(f"Failed to fetch URL: {url}")
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
            default_pattern = None
            for action, pattern in SOURCE_ACTIONS[prefix]:
                if action == '':
                    default_pattern = pattern  # Remember default
                elif action in task_lower:
                    return pattern
            # No specific action matched, use default if available
            if default_pattern:
                return default_pattern

    # No source or unknown prefix: use keyword + content hint matching
    input_lower = input_text.lower()[:1000]  # Only check first 1000 chars for hints

    for keywords, content_hints, pattern_name in AUTO_SELECT_RULES:
        # Rules with content_hints: ANY keyword match + ANY content hint match
        # Rules without content_hints: ALL keywords must match (more specific)
        if content_hints:
            # Content-aware rules: looser keyword matching, stricter content check
            if any(kw in task_lower for kw in keywords):
                if any(hint in input_lower for hint in content_hints):
                    return pattern_name
        else:
            # General rules: require all keywords for specificity
            if all(kw in task_lower for kw in keywords):
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


def prompt_fabric(task: str, pattern: str = "", input_text: str = "", source: str = "") -> str:
    """
    Run a Fabric AI pattern as an isolated subagent (230+ patterns available).

    Fabric patterns are specialized prompts for tasks like summarizing videos,
    extracting insights, analyzing security threats, or explaining code. Patterns
    run in isolation, keeping large content out of main conversation context.

    Args:
        task: Brief English description for auto-selection (e.g., "summarize", "extract wisdom").
              Used for auto-selecting the appropriate pattern.
        pattern: Specific pattern name to run. Optional - if omitted, auto-selects
                 based on task and source type.
                 Common patterns: extract_wisdom, youtube_summary, summarize_paper,
                 analyze_threat_report, explain_code, create_sigma_rules
        input_text: Text content to process. Prefer 'source' parameter instead
                    to keep large content out of conversation context.
        source: Content source URI (preferred over input_text). Formats:
                - yt:VIDEO_ID or yt:URL - YouTube video
                - pdf:/path or pdf:URL - PDF document
                - github:owner/repo or github:URL - GitHub repository
                - url:example.com/page - Web page
                - file:/path/to/file.md - Local text file

    Returns:
        XML-tagged output preserving Markdown formatting:
        - Success: <fabric_result pattern="name" auto_selected="true">CONTENT</fabric_result>
        - Error: <fabric_error pattern="name">ERROR MESSAGE</fabric_error>
        - Suggestions: <fabric_suggestions task="task">SUGGESTIONS</fabric_suggestions>

    Examples:
        # YouTube video
        prompt_fabric(task="summarize", source="yt:dQw4w9WgXcQ")

        # PDF with explicit pattern
        prompt_fabric(pattern="summarize_paper", source="pdf:~/paper.pdf")

        # GitHub repository
        prompt_fabric(task="analyze", source="github:anthropics/anthropic-sdk-python")

        # Pre-loaded content
        prompt_fabric(task="explain code", input_text="def hello(): print('world')")
    """
    # Load from source if provided (keeps content in isolated context)
    if source:
        try:
            input_text = _load_source(source)
        except Exception as e:
            return f'<fabric_error source="{_escape_xml_attr(source)}">\nFailed to load source: {e}\n</fabric_error>'

    # Validate input
    if not task and not pattern:
        return '<fabric_error type="validation">\nEither \'task\' or \'pattern\' must be provided.\nHint: Describe what you want to do, or specify a pattern name.\n</fabric_error>'

    # If explicit pattern provided, run it directly
    if pattern:
        pattern_name = pattern.strip()
        # Remove fabric: prefix if accidentally included
        if pattern_name.startswith("fabric:"):
            pattern_name = pattern_name[7:]

        try:
            result = _run_pattern(pattern_name, input_text)
            return f'<fabric_result pattern="{_escape_xml_attr(pattern_name)}">\n{result}\n</fabric_result>'
        except ValueError as e:
            return f'<fabric_error pattern="{_escape_xml_attr(pattern_name)}">\n{e}\nHint: Use prompt_fabric(task=\'describe what you want\') to get pattern suggestions.\n</fabric_error>'
        except Exception as e:
            return f'<fabric_error pattern="{_escape_xml_attr(pattern_name)}">\nPattern execution failed: {e}\n</fabric_error>'

    # Try auto-selection based on task
    selected_pattern = _auto_select_pattern(task, input_text, source)

    if selected_pattern:
        # Auto-selected a pattern, run it
        try:
            result = _run_pattern(selected_pattern, input_text)
            return f'<fabric_result pattern="{_escape_xml_attr(selected_pattern)}" auto_selected="true">\n{result}\n</fabric_result>'
        except Exception as e:
            return f'<fabric_error pattern="{_escape_xml_attr(selected_pattern)}" auto_selected="true">\nPattern execution failed: {e}\n</fabric_error>'

    # No clear match - get suggestions
    suggestions = _suggest_patterns(task)
    return f'<fabric_suggestions task="{_escape_xml_attr(task)}">\n{suggestions}\n\nHint: Call prompt_fabric(pattern=\'pattern_name\', input_text=content) with your chosen pattern.\n</fabric_suggestions>'


@llm.hookimpl
def register_tools(register):
    """Register the prompt_fabric tool with llm."""
    register(prompt_fabric)
