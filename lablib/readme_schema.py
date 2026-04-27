from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any
from urllib import error, parse, request

from lablib.readme_expectations import EXECUTABLE_COMMAND_FENCE_LANGUAGES, OUTPUT_FENCE_LANGUAGE, README_V2_H2_SEQUENCE


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
FENCED_CODE_BLOCK_RE = re.compile(r"```(?P<lang>[a-zA-Z0-9_-]+)?\s*\n(?P<body>.*?)```", re.DOTALL | re.MULTILINE)
HTML_COMMENT_RE = re.compile(r"<!--(?P<body>.*?)-->", re.DOTALL)
MARKDOWN_LINK_RE = re.compile(r"(!)?\[(?P<label>[^\]]*)\]\((?P<target>[^)]+)\)")
SHELL_COMMAND_PREFIXES_RE = re.compile(r"^(docker|python|python3|chmod|git|curl|cd|npm|pnpm|yarn|make|bash|sh)\b")
V2_SCHEMA_VERSION = "v2"
DEFAULT_REQUIRED_PHASES = ("baseline", "final")
OPTIONAL_PHASE_KINDS = ("intermediate", "studio", "inspection", "cleanup_verification")
ALLOWED_PHASE_KINDS = DEFAULT_REQUIRED_PHASES + OPTIONAL_PHASE_KINDS


def parse_required_phase_kinds(metadata: dict[str, Any]) -> list[str]:
    """Parse and merge required phase kinds from README metadata.

    Args:
        metadata: README frontmatter metadata dict

    Returns:
        List of required phase kinds (defaults + user-specified, no duplicates)
    """
    user_required = metadata.get("required_phases", [])

    # Normalize to list if it's a single string
    if isinstance(user_required, str):
        user_required = [user_required]

    # Merge: defaults + user-specified (avoiding duplicates)
    return list(DEFAULT_REQUIRED_PHASES) + [
        phase for phase in user_required if phase not in DEFAULT_REQUIRED_PHASES
    ]


@dataclass(frozen=True)
class Heading:
    level: int
    title: str
    line: int
    start: int


@dataclass(frozen=True)
class CodeBlock:
    language: str
    body: str
    line: int
    is_command: bool
    is_output: bool


@dataclass(frozen=True)
class MarkdownLink:
    label: str
    target: str
    line: int
    is_image: bool
    is_external: bool


@dataclass
class ReadmePhase:
    id: str
    title: str
    kind: str
    heading: Heading
    metadata: dict[str, Any]
    content: str
    code_blocks: list[CodeBlock] = field(default_factory=list)
    links: list[MarkdownLink] = field(default_factory=list)

    @property
    def command_blocks(self) -> list[CodeBlock]:
        return [block for block in self.code_blocks if block.is_command]

    @property
    def output_blocks(self) -> list[CodeBlock]:
        return [block for block in self.code_blocks if block.is_output]


@dataclass
class ReadmeDocument:
    text: str
    body_text: str
    metadata: dict[str, Any]
    schema_version: str | None
    headings: list[Heading]
    h1_title: str
    h2_titles: list[str]
    phases: list[ReadmePhase]
    links: list[MarkdownLink]

    @property
    def is_v2(self) -> bool:
        return self.schema_version == V2_SCHEMA_VERSION

    def phase_by_id(self, phase_id: str | None) -> ReadmePhase | None:
        if not phase_id:
            return None
        for phase in self.phases:
            if phase.id == phase_id:
                return phase
        return None


def parse_readme_document(text: str) -> ReadmeDocument:
    metadata, body_text = extract_front_matter(text)
    headings = extract_headings(body_text)
    h1_title = next((heading.title for heading in headings if heading.level == 1), "")
    h2_titles = [heading.title for heading in headings if heading.level == 2]
    phases = extract_v2_phases(body_text, headings) if metadata.get("lab_schema") == V2_SCHEMA_VERSION else []
    links = extract_markdown_links(body_text)
    return ReadmeDocument(
        text=text,
        body_text=body_text,
        metadata=metadata,
        schema_version=metadata.get("lab_schema"),
        headings=headings,
        h1_title=h1_title,
        h2_titles=h2_titles,
        phases=phases,
        links=links,
    )


def extract_front_matter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    payload = text[4:end]
    body = text[end + 5 :]
    return parse_simple_yaml(payload), body


def extract_headings(text: str) -> list[Heading]:
    return [
        Heading(
            level=len(match.group(1)),
            title=match.group(2).strip(),
            line=line_number_for_index(text, match.start()),
            start=match.start(),
        )
        for match in HEADING_RE.finditer(text)
    ]


def extract_v2_phases(text: str, headings: list[Heading]) -> list[ReadmePhase]:
    implementation_h2 = next((heading for heading in headings if heading.level == 2 and heading.title == "Lab Implementation Phases"), None)
    if implementation_h2 is None:
        return []
    implementation_end = next((heading.start for heading in headings if heading.level == 2 and heading.start > implementation_h2.start), len(text))

    phase_headings = [
        heading
        for heading in headings
        if heading.level == 3 and implementation_h2.start < heading.start < implementation_end
    ]
    phases: list[ReadmePhase] = []
    for index, heading in enumerate(phase_headings):
        next_heading = phase_headings[index + 1] if index + 1 < len(phase_headings) else None
        section_start = heading.start
        section_end = next_heading.start if next_heading is not None else implementation_end
        section_text = text[section_start:section_end].strip()
        metadata = extract_phase_metadata(section_text)
        phase_id = str(metadata.get("id", "")).strip()
        phase_kind = str(metadata.get("kind", "")).strip()
        phases.append(
            ReadmePhase(
                id=phase_id,
                title=heading.title,
                kind=phase_kind,
                heading=heading,
                metadata=metadata,
                content=section_text,
                code_blocks=extract_code_blocks(section_text),
                links=extract_markdown_links(section_text),
            )
        )
    return phases


def extract_phase_metadata(section_text: str) -> dict[str, Any]:
    first_comment = next(HTML_COMMENT_RE.finditer(section_text), None)
    if first_comment is None:
        return {}
    body = first_comment.group("body").strip()
    if body.startswith("phase-meta"):
        body = body[len("phase-meta") :].strip()
    return parse_simple_yaml(body)


def extract_code_blocks(text: str) -> list[CodeBlock]:
    blocks: list[CodeBlock] = []
    for match in FENCED_CODE_BLOCK_RE.finditer(text):
        language = (match.group("lang") or "").strip().lower()
        body = match.group("body").strip()
        lines = [line.strip() for line in body.splitlines() if line.strip()]
        preview = lines[0] if lines else ""
        blocks.append(
            CodeBlock(
                language=language,
                body=body,
                line=line_number_for_index(text, match.start()),
                is_command=bool(lines and SHELL_COMMAND_PREFIXES_RE.match(preview)),
                is_output=language == OUTPUT_FENCE_LANGUAGE,
            )
        )
    return blocks


def extract_markdown_links(text: str) -> list[MarkdownLink]:
    links: list[MarkdownLink] = []
    for match in MARKDOWN_LINK_RE.finditer(text):
        target = match.group("target").strip()
        links.append(
            MarkdownLink(
                label=match.group("label"),
                target=target,
                line=line_number_for_index(text, match.start()),
                is_image=bool(match.group(1)),
                is_external=target.startswith("http://") or target.startswith("https://"),
            )
        )
    return links


def validate_internal_link(link: MarkdownLink, *, readme_path: Path, headings: list[Heading]) -> tuple[bool, str]:
    parsed = parse.urlparse(link.target)
    path_part = parsed.path
    fragment = parsed.fragment
    if not path_part and fragment:
        ok = fragment in heading_anchors(headings)
        return ok, f"Anchor #{fragment}"
    if path_part:
        candidate = (readme_path.parent / path_part).resolve()
        if not candidate.exists():
            return False, str(candidate)
        if fragment:
            if candidate.name.lower() == "readme.md":
                text = candidate.read_text(encoding="utf-8")
                linked_headings = extract_headings(strip_front_matter(text))
                ok = fragment in heading_anchors(linked_headings)
                return ok, f"{candidate}#{fragment}"
        return True, str(candidate)
    return True, link.target


def validate_external_link(target: str, *, timeout_seconds: float = 5.0, retries: int = 2) -> tuple[bool, str]:
    headers = {"User-Agent": "labs-tests/README-link-checker"}
    last_error = ""
    for _ in range(retries + 1):
        for method in ("HEAD", "GET"):
            try:
                req = request.Request(target, method=method, headers=headers)
                with request.urlopen(req, timeout=timeout_seconds) as response:
                    status = getattr(response, "status", 200)
                    if 200 <= status < 400:
                        return True, f"HTTP {status}"
                    last_error = f"HTTP {status}"
            except error.HTTPError as exc:
                if 200 <= exc.code < 400:
                    return True, f"HTTP {exc.code}"
                if exc.code == 405 and method == "HEAD":
                    continue
                last_error = f"HTTP {exc.code}"
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
    return False, last_error or "Request failed"


def phase_sequence_is_valid(
    phases: list[ReadmePhase],
    required_phase_kinds: list[str]
) -> tuple[bool, str]:
    """Validate phase sequence including required phase kinds.

    Args:
        phases: List of phases to validate
        required_phase_kinds: List of required phase kinds (already merged with defaults).

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not phases:
        return False, "No H3 phases were found under 'Lab Implementation Phases'."

    kinds = [phase.kind for phase in phases]

    # Baseline and final are always required
    if kinds.count("baseline") != 1:
        return False, f"Expected exactly one baseline phase, found {kinds.count('baseline')}."
    if kinds.count("final") != 1:
        return False, f"Expected exactly one final phase, found {kinds.count('final')}."

    # Validate first and last phase positions
    if kinds[0] != "baseline":
        return False, "The first lab phase must be the baseline phase."
    if kinds[-1] != "final":
        return False, "The last lab phase must be the final phase."

    # Check required phases from top-level metadata
    for required_kind in required_phase_kinds:
        if required_kind not in DEFAULT_REQUIRED_PHASES and kinds.count(required_kind) < 1:
            return False, f"Phase kind '{required_kind}' is marked as required but not found in README."

    # Check for unsupported phase kinds
    invalid = [phase.kind for phase in phases if phase.kind not in ALLOWED_PHASE_KINDS]
    if invalid:
        return False, f"Found unsupported phase kinds: {', '.join(invalid)}."

    return True, "Phase sequence is valid."


def strip_front_matter(text: str) -> str:
    return extract_front_matter(text)[1]


def heading_anchors(headings: list[Heading]) -> set[str]:
    return {github_anchor(heading.title) for heading in headings}


def github_anchor(title: str) -> str:
    normalized = re.sub(r"[^\w\s-]", "", title.strip().lower())
    normalized = re.sub(r"\s+", "-", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized)
    return normalized.strip("-")


def line_number_for_index(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def parse_simple_yaml(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    value, _ = parse_yaml_node(lines, 0, 0)
    return value or {}


def parse_yaml_node(lines: list[str], index: int, indent: int) -> tuple[Any, int]:
    index = skip_yaml_noise(lines, index)
    if index >= len(lines):
        return None, index
    current_indent = yaml_indent(lines[index])
    if current_indent < indent:
        return None, index
    stripped = lines[index].strip()
    if stripped.startswith("- "):
        return parse_yaml_sequence(lines, index, current_indent)
    return parse_yaml_mapping(lines, index, current_indent)


def parse_yaml_mapping(lines: list[str], index: int, indent: int) -> tuple[dict[str, Any], int]:
    mapping: dict[str, Any] = {}
    while True:
        index = skip_yaml_noise(lines, index)
        if index >= len(lines):
            break
        current_indent = yaml_indent(lines[index])
        if current_indent < indent:
            break
        if current_indent > indent:
            break
        stripped = lines[index].strip()
        if stripped.startswith("- "):
            break
        key, value = split_yaml_key_value(stripped)
        index += 1
        if value is None:
            child, index = parse_yaml_node(lines, index, indent + 2)
            mapping[key] = child
        else:
            mapping[key] = parse_yaml_scalar(value)
    return mapping, index


def parse_yaml_sequence(lines: list[str], index: int, indent: int) -> tuple[list[Any], int]:
    items: list[Any] = []
    while True:
        index = skip_yaml_noise(lines, index)
        if index >= len(lines):
            break
        current_indent = yaml_indent(lines[index])
        if current_indent < indent:
            break
        stripped = lines[index].strip()
        if current_indent != indent or not stripped.startswith("- "):
            break
        entry = stripped[2:].strip()
        index += 1
        if not entry:
            child, index = parse_yaml_node(lines, index, indent + 2)
            items.append(child)
            continue
        if ":" in entry and not entry.startswith(("'", '"')):
            key, value = split_yaml_key_value(entry)
            item: dict[str, Any] = {}
            if value is None:
                child, index = parse_yaml_node(lines, index, indent + 2)
                item[key] = child
            else:
                item[key] = parse_yaml_scalar(value)
            extra, index = parse_yaml_mapping(lines, index, indent + 2)
            item.update(extra)
            items.append(item)
            continue
        items.append(parse_yaml_scalar(entry))
    return items, index


def split_yaml_key_value(text: str) -> tuple[str, str | None]:
    key, _, raw_value = text.partition(":")
    value = raw_value.strip()
    return key.strip(), value or None


def parse_yaml_scalar(value: str) -> Any:
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none"}:
        return None
    if value.startswith(("'", '"')) and value.endswith(("'", '"')) and len(value) >= 2:
        return value[1:-1]
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    return value


def skip_yaml_noise(lines: list[str], index: int) -> int:
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped and not stripped.startswith("#"):
            return index
        index += 1
    return index


def yaml_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def expected_h2_titles_for_document(document: ReadmeDocument) -> tuple[str, ...]:
    if document.is_v2:
        return README_V2_H2_SEQUENCE
    return tuple()


def command_fence_languages() -> set[str]:
    return set(EXECUTABLE_COMMAND_FENCE_LANGUAGES)
