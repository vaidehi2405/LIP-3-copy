def to_bold(text: str) -> str:
    res = []
    for c in text:
        if 'A' <= c <= 'Z':
            res.append(chr(ord(c) - ord('A') + 0x1D5D4))
        elif 'a' <= c <= 'z':
            res.append(chr(ord(c) - ord('a') + 0x1D5EE))
        elif '0' <= c <= '9':
            res.append(chr(ord(c) - ord('0') + 0x1D7E2))
        else:
            res.append(c)
    return "".join(res)

def to_italic(text: str) -> str:
    res = []
    for c in text:
        if 'A' <= c <= 'Z':
            res.append(chr(ord(c) - ord('A') + 0x1D608))
        elif 'a' <= c <= 'z':
            # Note: h is an exception 0x210E, but mostly contiguous 0x1D622
            res.append(chr(ord(c) - ord('a') + 0x1D622))
        else:
            res.append(c)
    return "".join(res)

def to_underline(text: str) -> str:
    # Character followed by combining macron below (U+0332)
    return "".join(c + '\u0332' for c in text)

print(to_bold("Weekly App Review Pulse"))
print(to_bold("Top Themes This Week"))
print(to_underline("Suggested Actions"))
print(to_italic('"User friendly"'))
