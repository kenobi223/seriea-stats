"""Test: /opencode handler → _apply_fixes matching."""

_APPLY_MAP = {
    "service worker": lambda: "sw.js creato",
    "sw.js": lambda: "sw.js creato",
    "manifest": lambda: "manifest.json creato",
    "pwa manifest": lambda: "manifest.json creato",
}


def _apply_fixes(fixes):
    applied = []
    for fix in fixes:
        key = fix.strip().lower()
        handler = None
        for pattern, fn in _APPLY_MAP.items():
            if pattern in key:
                handler = fn
                break
        applied.append({"fix": fix, "matched": handler is not None})
    return applied


# --- /opencode stores raw user text ---
cases = [
    # (user input after /opencode, expected match)
    ("service worker", True),
    ("sw.js", True),
    ("manifest", True),
    ("pwa manifest", True),
    ("aggiungi service worker", True),       # substring match works
    ("crea il manifest per PWA", True),      # substring match works
    ("fix caching bug", False),              # no pattern matches
    ("optimize database queries", False),    # no pattern matches
]

print("=" * 60)
print("TEST: /opencode -> _apply_fixes matching")
print("=" * 60)

all_pass = True
for user_input, expected in cases:
    fixes_from_user = [user_input]
    results = _apply_fixes(fixes_from_user)
    matched = results[0]["matched"]
    status = "PASS" if matched == expected else "FAIL"
    if status == "FAIL":
        all_pass = False
    print(f"  [{status}] /opencode {user_input!r}")
    print(f"         fixes={fixes_from_user} -> matched={matched} (expected={expected})")

print("=" * 60)

if all_pass:
    print("RESULT: No mismatch for standard _APPLY_MAP keys.")
    print("The substring check ('pattern in key') handles common cases.")
else:
    print("RESULT: MISMATCH FOUND")

print()
print("CONCLUSION:")
print("  /opencode stores raw user text as [req].")
print("  _apply_fixes does 'if pattern in key' (substring).")
print("  If user types '/opencode service worker' -> 'service worker' in 'service worker' -> MATCH")
print("  If user types '/opencode optimize DB' -> no key substring found -> SILENT NO-OP")
print("  The fix runs but no file changes -> git diff --cached --quiet -> nothing pushed.")
