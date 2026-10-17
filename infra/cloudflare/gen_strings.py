# -*- coding: utf-8 -*-
"""Genera infra/cloudflare/tg_strings.js da app/i18n.py (T["it"] + DONATION_OPTIONS).

Il Worker usa le stesse stringhe italiane del bot Render: l'unico formato è
questo modulo generato, così i testi non possono divergere dall'i18n Python.

Uso:
    python infra/cloudflare/gen_strings.py           # riscrive tg_strings.js
    python infra/cloudflare/gen_strings.py --check   # verifica, exit 1 se diff
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from app.i18n import DONATION_OPTIONS, T  # noqa: E402


def render():
    it = T["it"]
    body = ",\n".join(
        "  %s: %s" % (json.dumps(k, ensure_ascii=False),
                      json.dumps(v, ensure_ascii=False))
        for k, v in sorted(it.items()))
    return "\n".join([
        '// GENERATED FILE da app/i18n.py via gen_strings.py — non modificare a mano.',
        '// Rigenera con: python infra/cloudflare/gen_strings.py',
        "",
        "export const T = {\n%s,\n};" % body,
        "",
        "export const DONATION_OPTIONS = [%s];"
        % ", ".join(str(x) for x in DONATION_OPTIONS),
        "",
    ])


def main():
    out = os.path.join(HERE, "tg_strings.js")
    text = render()
    if "--check" in sys.argv:
        cur = None
        try:
            with open(out, "r", encoding="utf-8") as f:
                cur = f.read()
        except OSError:
            pass
        if cur != text:
            print("tg_strings.js DESINCRONIZZATO da app/i18n.py")
            sys.exit(1)
        print("tg_strings.js ok (%d chiavi)" % len(T["it"]))
        return
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("scritto %s (%d chiavi)" % (out, len(T["it"])))


if __name__ == "__main__":
    main()
