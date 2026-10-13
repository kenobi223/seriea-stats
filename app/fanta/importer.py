"""Import rosa da CSV esportato da Leghe Fantacalcio (e formati simili).

Il parser è volutamente tollerante:
- rileva encoding (utf-8 / utf-8-sig / latin-1) e delimitatore (`;`, `,`, tab)
- riconosce le intestazioni in italiano o inglese (Ruolo/Nome/Squadra/...)
- in assenza di intestazioni assume l'ordine classico: Ruolo, Nome, Squadra
- normalizza i ruoli: P/POR/1/Portiere -> P, D/DIF/2 -> D, C/CEN/3 -> C,
  A/ATT/4 -> A
- abbina ogni giocatore all'indice fantacalcio.it per COGNOME + INIZIALE,
  disambiguando con la squadra; i non riconosciuti vengono segnalati.
"""
import csv
import io
import logging
import re
import unicodedata

log = logging.getLogger("fanta.importer")

# sinonimi di intestazione per colonna
_HEADER_MAP = {
    "role": ("ruolo", "role", "r", "pos", "posizione", "ruolo classico"),
    "name": ("nome", "calciatore", "giocatore", "name", "player",
             "descrizione", "nominativo"),
    "team": ("squadra", "team", "sq", "societa", "club", "squadra serie a"),
    "price": ("quotazione", "quot", "qt", "qa", "qi", "prezzo", "costo",
              "fvm", "value", "valore", "quotazione attuale"),
}

_ROLE_WORDS = {
    "p": "P", "por": "P", "porc": "P", "portiere": "P", "goalkeeper": "P",
    "gk": "P", "1": "P",
    "d": "D", "dif": "D", "difc": "D", "difensore": "D", "defender": "D",
    "df": "D", "2": "D",
    "c": "C", "cen": "C", "centrocampista": "C", "midfielder": "C",
    "mid": "C", "m": "C", "3": "C",
    "a": "A", "att": "A", "attaccante": "A", "attacker": "A", "for": "A",
    "forward": "A", "fw": "A", "striker": "A", "4": "A",
}


def _norm(s):
    """minuscole, senza accenti, solo lettere/numeri/spazi."""
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _role(value):
    v = _norm(value).replace(" ", "")
    if v in _ROLE_WORDS:
        return _ROLE_WORDS[v]
    if v[:3] in _ROLE_WORDS:
        return _ROLE_WORDS[v[:3]]
    if v[:1] in ("p", "d", "c", "a"):
        return v[:1].upper()
    return "?"


def looks_like_header(cells):
    joined = " ".join(_norm(c) for c in cells)
    hits = 0
    for syns in _HEADER_MAP.values():
        if any(s in joined for s in syns):
            hits += 1
    return hits >= 2


def detect_delimiter(sample):
    counts = {d: sample.count(d) for d in (";", ",", "\t", "|")}
    best = max(counts, key=counts.get)
    return best if counts[best] else ","


def parse_csv(raw):
    """Ritorna (righe, meta). righe = [{name, role, team, price}].

    raw: str (testo del file). Ritorna anche eventuali problemi.
    """
    if isinstance(raw, bytes):
        for enc in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                raw = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raw = raw.decode("latin-1", "replace")
    raw = raw.replace("\r\n", "\n").replace("\r", "\n").strip("\n\ufeff")
    if not raw.strip():
        return [], {"error": "file vuoto"}
    first_lines = "\n".join(raw.splitlines()[:10])
    delim = detect_delimiter(first_lines)
    reader = csv.reader(io.StringIO(raw), delimiter=delim)
    rows = [r for r in reader if any((c or "").strip() for c in r)]
    if not rows:
        return [], {"error": "nessuna riga"}

    header = None
    ncols = len(rows[0])
    if looks_like_header(rows[0]):
        header = [_norm(c) for c in rows[0]]
        data_rows = rows[1:]
    else:
        data_rows = rows

    def col_index(keys):
        if header is None:
            return None
        for i, h in enumerate(header):
            for syn in keys:
                if h == syn or h.startswith(syn) or syn in h:
                    return i
        return None

    idx_name = col_index(_HEADER_MAP["name"])
    idx_role = col_index(_HEADER_MAP["role"])
    idx_team = col_index(_HEADER_MAP["team"])
    idx_price = col_index(_HEADER_MAP["price"])

    out = []
    for r in data_rows:
        cells = [(c or "").strip() for c in r]
        if len(cells) < 2:
            continue
        if header is not None:
            name = cells[idx_name] if idx_name is not None and idx_name < len(cells) else ""
            role = cells[idx_role] if idx_role is not None and idx_role < len(cells) else ""
            team = cells[idx_team] if idx_team is not None and idx_team < len(cells) else ""
            price = cells[idx_price] if idx_price is not None and idx_price < len(cells) else ""
        else:
            # ordine posizionale classico (Ruolo, Nome, Squadra[, Quotazione])
            role, name = cells[0], cells[1]
            team = cells[2] if len(cells) > 2 else ""
            price = cells[3] if len(cells) > 3 else ""
        role_c = _role(role)
        # se il ruolo non è riconoscibile per posizione, prova a dedurlo
        if role_c == "?" and not name:
            continue
        if not name:
            name, role_c = role, "?"
        if role_c == "?" and _role(team) != "?" and not any(
                ch.isdigit() for ch in team):
            # possibile colonne invertite: prova a scambiarle
            pass
        out.append({"name": name, "role": role_c,
                    "team": team, "price": price})
    return out, {"delimiter": delim, "header": header, "rows": len(out)}


def _split_index_name(name):
    """'Martinez L.' -> (['martinez'], ['l']) ; 'Di Gregorio' -> (['di','gregorio'], [])."""
    toks = _norm(name).split()
    initials = []
    while len(toks) > 1 and len(toks[-1]) == 1:
        initials.insert(0, toks.pop())
    return toks, initials


def _find_subseq(haystack, needle):
    """True se needle compare consecutivamente in haystack."""
    n, m = len(haystack), len(needle)
    if m == 0 or m > n:
        return False
    for i in range(n - m + 1):
        if haystack[i:i + m] == needle:
            return True
    return False


def match_row(row, index):
    """Abbina una riga CSV a un giocatore dell'indice.

    Ritorna (player, status) dove status in {'matched','ambiguous','missing'}.
    """
    name_tokens = _norm(row.get("name")).split()
    if not name_tokens:
        return None, "missing"
    row_team = _norm(row.get("team"))
    candidates = []
    for p in index:
        p_toks, p_initials = _split_index_name(p.get("name"))
        if not p_toks or not _find_subseq(name_tokens, p_toks):
            continue
        score = 3                                  # cognome presente
        # iniziali: ogni iniziale deve combaciare con l'inizio di un token
        # del nome esportato non facente parte del cognome
        rest = name_tokens[:]
        for t in p_toks:
            if t in rest:
                rest.remove(t)
        if p_initials:
            ok = True
            used = 0
            for ini in p_initials:
                hit = any(t.startswith(ini) for t in rest[used:]) or \
                    any(t.startswith(ini) for t in rest)
                if not hit:
                    ok = False
                    break
                used += 1
            if ok:
                score += 2
        else:
            score += 1                          # senza iniziali: cognome basta
        # squadra: sigla o nome completo
        if row_team:
            p_abbr = _norm(p.get("team_abbr"))
            p_team = _norm(p.get("team"))
            if row_team and (row_team == p_abbr or row_team == p_team or
                             row_team in p_team or p_abbr.startswith(row_team)):
                score += 2
        candidates.append((score, p))
    if not candidates:
        return None, "missing"
    candidates.sort(key=lambda x: -x[0])
    top = candidates[0]
    if top[0] < 3:
        return None, "missing"
    if len(candidates) > 1 and candidates[1][0] == top[0]:
        return top[1], "ambiguous"
    return top[1], "matched"


def import_rows(rows, index):
    """Abbina tutte le righe. Ritorna dict con matched/ambiguous/missing."""
    matched, ambiguous, missing = [], [], []
    seen_ids = set()
    for row in rows:
        player, status = match_row(row, index)
        if status == "missing" or player is None:
            missing.append(row)
            continue
        entry = {
            "id": player["id"],
            "name": player["name"],
            "team": player["team"],
            "role": player["role"],          # ruolo ufficiale dell'indice
            "csv_role": row.get("role"),
            "csv_name": row.get("name"),
        }
        if status == "ambiguous":
            ambiguous.append(entry)
            continue
        if entry["id"] in seen_ids:
            continue
        seen_ids.add(entry["id"])
        matched.append(entry)
    return {"matched": matched, "ambiguous": ambiguous, "missing": missing}
