"""
LLM tools for Fabric pattern integration.

Provides the `fabric` tool for executing Fabric AI patterns as isolated subagents.
Supports auto-selection of patterns based on task description, or explicit pattern
specification. Works standalone with llm CLI or integrated with llm-sidechat.

Fabric patterns are specialized AI prompts from https://github.com/danielmiessler/fabric
"""
import json
import re
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


def _auto_select_pattern(task: str, input_text: str = "") -> Optional[str]:
    """
    Auto-select a Fabric pattern based on task description and input content.

    Returns pattern name if a clear match is found, None otherwise.
    """
    task_lower = task.lower()
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


def fabric(task: str, pattern: str = "", input_text: str = "") -> str:
    """
    Execute a Fabric pattern or get pattern recommendations.

    Fabric patterns are specialized AI prompts for common tasks like summarization,
    analysis, extraction, and content creation. This tool runs patterns in isolation,
    so they don't affect the main conversation context.

    Args:
        task: Description of what to accomplish (e.g., "summarize this video",
              "analyze threat report", "extract key insights", "explain code").
              Used for auto-selecting the appropriate pattern.
        pattern: (Optional) Specific pattern name to run. If not provided,
                 auto-selects based on task or suggests options.
                 Examples: extract_wisdom, youtube_summary, analyze_threat_report,
                 summarize_paper, explain_code, create_sigma_rules
        input_text: Content to process with the pattern. This should be the actual
                   text content (use load_yt, load_pdf, load_github first to extract).

    Returns:
        The processed result from the Fabric pattern, or pattern suggestions
        if no clear pattern match is found.

    Examples:
        # With explicit pattern
        fabric(task="", pattern="extract_wisdom", input_text=transcript)

        # With auto-selection
        fabric(task="summarize this YouTube video", input_text=transcript)

        # Get suggestions for ambiguous request
        fabric(task="process this document", input_text=doc_text)
    """
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
    selected_pattern = _auto_select_pattern(task, input_text)

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
