import ast
import re
import tokenize
from io import StringIO
from urllib.parse import urlparse

_SECRET_TOKEN = r"\b(?:sk-|gh[pousr]_|github_pat_|tk-us-)[A-Za-z0-9_-]{12,}"
_LOG_SECRET = re.compile(
    r"""(?i)\b(?:authorization|api[-_ ]?key|password|secret|token)\b["']?\s*[:=]\s*"""
    r"""(?:"[^"]*"|'[^']*'|(?:bearer|basic)\s+[^\s,;]+|[^\s,;"']+)"""
    rf"|{_SECRET_TOKEN}"
)
_SOURCE_FIELD = re.compile(
    r"(?:[a-z0-9]+_)*(?:authorization|api[-_ ]?key|password|secret|token)",
    re.IGNORECASE,
)
_SOURCE_QUOTE = re.compile(r"""[bru]*(?P<quote>'{3}|"{3}|'|")""", re.IGNORECASE)
_SOURCE_SECRET = re.compile(
    r"""(?P<assignment>\b(?:[a-z0-9]+_)*(?:authorization|api[-_ ]?key|password|secret|token)\b["']?"""
    r"[ \t]*[:=][ \t]*[bruf]{0,2})"
    r"""(?P<quote>'{3}|"{3}|'|")(?:\\[\s\S]|(?!(?P=quote))[^\\])*?(?P=quote)""",
    re.IGNORECASE,
)


def _credential_value_index(tokens: list[tokenize.TokenInfo], index: int) -> int | None:
    field = tokens[index]
    if field.type == tokenize.NAME and _SOURCE_FIELD.fullmatch(field.string):
        index += 1
        if tokens[index].string == ":":
            depth = 0
            for index in range(index + 1, len(tokens)):
                token = tokens[index]
                if token.type == tokenize.NEWLINE or (
                    depth == 0 and token.string in {"=", ";", ",", ")", "]", "}"}
                ):
                    break
                if token.string in {"(", "[", "{"}:
                    depth += 1
                elif token.string in {")", "]", "}"}:
                    depth -= 1
        return index + 1 if tokens[index].string == "=" else None
    if field.type == tokenize.STRING and len(field.string) <= 128:
        if tokens[index + 1].string == ":":
            value_index = index + 2
        elif index > 0 and tokens[index - 1].string == "[" and [
            token.string for token in tokens[index + 1:index + 3]
        ] == ["]", "="]:
            value_index = index + 3
        else:
            return None
        try:
            name = ast.literal_eval(field.string)
        except (SyntaxError, ValueError):
            return None
        if isinstance(name, str) and _SOURCE_FIELD.fullmatch(name):
            return value_index
    return None


def _redact_source(value: str) -> str:
    if not _SOURCE_FIELD.search(value):
        return value
    tokens = []
    try:
        for token in tokenize.generate_tokens(StringIO(value).readline):
            if token.type not in {tokenize.NL, tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT}:
                tokens.append(token)
    except (tokenize.TokenError, IndentationError):
        # A diff hunk or a draft edit can end in the middle of a Python construct.
        pass

    lines = StringIO(value).readlines()
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    replacements = {}
    for index in range(len(tokens) - 1):
        start = _credential_value_index(tokens, index)
        if start is None:
            continue
        while start < len(tokens) and tokens[start].string == "(":
            start += 1
        for token in tokens[start:]:
            if token.type != tokenize.STRING:
                break
            quote = _SOURCE_QUOTE.match(token.string)
            if quote:
                left = offsets[token.start[0] - 1] + token.start[1]
                right = offsets[token.end[0] - 1] + token.end[1]
                newlines = "".join(re.findall(r"\r?\n", token.string))
                replacements[left, right] = quote[0] + "[REDACTED]" + newlines + quote["quote"]

    for (left, right), replacement in sorted(replacements.items(), reverse=True):
        value = value[:left] + replacement + value[right:]
    return _SOURCE_SECRET.sub(
        lambda match: match["assignment"] + match["quote"] + "[REDACTED]"
        + "".join(re.findall(r"\r?\n", match[0])) + match["quote"],
        value,
    )


def _redact_diff(value: str) -> str:
    lines = StringIO(value).readlines()
    changed = lines.copy()
    hunk = []
    # Keep the old and new contexts separate when a credential spans diff lines.
    for index, line in enumerate([*lines, "@@"]):
        if line.startswith(("@@", "diff --git ")):
            for markers in (" -", " +"):
                side = [(row, lines[row][1:]) for row in hunk if lines[row][0] in markers]
                masked = _redact_source("".join(text for _, text in side))
                for (row, original), redacted in zip(side, StringIO(masked).readlines(), strict=True):
                    if redacted != original:
                        changed[row] = lines[row][0] + redacted
            hunk.clear()
        elif line and line[0] in " +-" and not line.startswith(("--- ", "+++ ")):
            hunk.append(index)
    return "".join(changed)


def _redact_text(value: str, secrets, *, source: str = "") -> str:
    for secret in secrets:
        value = value.replace(secret, "[REDACTED]")
    if not source:
        return _LOG_SECRET.sub("[REDACTED]", value)
    value = re.sub(_SECRET_TOKEN, "[REDACTED]", value, flags=re.IGNORECASE)
    return _redact_diff(value) if source == "diff" else _redact_source(value)


def redact(value, secrets=()):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key == "validated_changes":
                continue
            is_source = isinstance(key, str) and (key.endswith(".py") or key == "diff")
            result[key] = (
                _redact_text(item, secrets, source=key)
                if is_source and isinstance(item, str)
                else redact(item, secrets)
            )
        return result
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    if not isinstance(value, str):
        return value
    return _redact_text(value, secrets)


def review_url_allowed(url: str, extra_hosts: list[str]) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    return (
        parsed.scheme == "https"
        and parsed.port in (None, 443)
        and parsed.username is None
        and parsed.password is None
        and parsed.path in ("", "/")
        and not parsed.query
        and not parsed.fragment
        and (host.endswith(".scalingo.io") or host in extra_hosts)
    )
