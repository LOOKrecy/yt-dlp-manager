from __future__ import annotations

import locale


def candidate_output_encodings() -> list[str]:
    candidates = ["utf-8", locale.getpreferredencoding(False), "mbcs", "cp1251"]
    result: list[str] = []
    for encoding in candidates:
        if encoding and encoding not in result:
            result.append(encoding)
    return result


def decode_process_output(data: bytes) -> str:
    if not data:
        return ""
    encodings = candidate_output_encodings()
    best_text = ""
    best_replacements = 10**9
    for encoding in encodings:
        try:
            text = data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
        replacements = text.count("\ufffd")
        if replacements < best_replacements:
            best_text = text
            best_replacements = replacements
        if replacements == 0:
            return text
    if best_text:
        return best_text
    return data.decode("utf-8", errors="replace")
