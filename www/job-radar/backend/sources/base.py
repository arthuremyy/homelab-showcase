"""
Contrat commun à tous les connecteurs de sources.

Un connecteur expose `async def fetch(params: dict) -> list[dict]` et rend des
offres NORMALISÉES. Toute la logique spécifique à une source (pagination, codes
maison, format de date) reste dans le connecteur : le reste du service ne voit
que ce dictionnaire.

Champs normalisés :
    source, source_id, url, title, company, location, dept, remote,
    contract_type, salary_raw, salary_min, salary_max, description,
    posted_at (ISO 8601), _raw (dict brut conservé pour le scoring et le débogage)
"""
import re

HEADERS = {
    # User-Agent honnête : veille personnelle, faible volume, pas de dissimulation.
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

TIMEOUT = 30.0

AURA_DEPTS = {"01", "03", "07", "15", "26", "38", "42", "43", "63", "69", "73", "74"}

CONTRACT_PATTERNS = [
    ("alternance", r"\balternan|\bapprenti|\bcontrat pro"),
    ("stage",      r"\bstage\b|\bstagiaire\b"),
    ("interim",    r"\bint[ée]rim\b"),
    ("cdd",        r"\bcdd\b|dur[ée]e d[ée]termin[ée]e"),
    ("cdi",        r"\bcdi\b|dur[ée]e ind[ée]termin[ée]e"),
]

# Le VIE se détecte à part, SANS passer le texte en minuscules : « vie » est un mot
# français courant (« qualité de vie », « assurance vie ») et un motif insensible à
# la casse étiquetait des centaines de CDI en VIE. Seul l'acronyme en capitales,
# ou la forme développée, comptent.
VIE_ACRONYM = re.compile(r"\bV\.?I\.?E\.?\b")
VIE_PHRASE = re.compile(r"volontariat international", re.I)


def infer_contract(text: str, fallback: str = "unknown") -> str:
    """Déduit le type de contrat du TEXTE. Dernier recours uniquement.

    À n'appeler que lorsque la source n'expose pas de champ structuré exploitable :
    le texte ment. « FREELANCE - FORMATEUR EN ADMINISTRATION » était classé en
    alternance parce que sa description parle d'encadrer des alternants, et un poste
    cyber mentionnant « vous encadrerez des alternants » subissait le même sort —
    soit -30 au matching sur une offre parfaitement valide.

    L'ordre compte : « alternance en CDD » doit sortir alternance, donc les formes
    les plus spécifiques passent d'abord."""
    raw = text or ""
    t = raw.lower()
    for label, pat in CONTRACT_PATTERNS[:2]:          # alternance et stage priment
        if re.search(pat, t):
            return label
    if VIE_ACRONYM.search(raw) or VIE_PHRASE.search(raw):
        return "vie"
    for label, pat in CONTRACT_PATTERNS[2:]:
        if re.search(pat, t):
            return label
    return fallback


# Codes d'exigence d'expérience France Travail.
XP_LEVELS = {"D": "debutant", "S": "souhaitee", "E": "exigee"}


def parse_xp_label(label: str | None) -> int | None:
    """« Débutant accepté » → 0 ; « 3 An(s) » → 3 ; « Expérience exigée » → None.

    Le libellé de la source est autoritatif : bien plus fiable que de deviner
    les années au regex dans une description de 3 000 caractères.
    """
    if not label:
        return None
    t = label.lower()
    if "débutant" in t or "debutant" in t:
        return 0
    m = re.search(r"(\d+)\s*an", t)
    if m:
        v = int(m.group(1))
        return v if 0 <= v <= 20 else None
    if "mois" in t:
        return 0          # moins d'un an d'expérience : équivalent junior
    return None


# Départements AURA écrits en toutes lettres (Adzuna `location.area`,
# Jooble : « Bron, Rhône »).
DEPT_BY_NAME = {
    "ain": "01", "allier": "03", "ardèche": "07", "cantal": "15", "drôme": "26",
    "isère": "38", "loire": "42", "haute-loire": "43", "puy-de-dôme": "63",
    "rhône": "69", "savoie": "73", "haute-savoie": "74",
}

# Villes publiées sans département (« Lyon » seul chez Jooble).
CITY_DEPT = {
    "lyon": "69", "villeurbanne": "69", "grenoble": "38", "saint-étienne": "42",
    "clermont-ferrand": "63", "annecy": "74", "chambéry": "73", "valence": "26",
}


def dept_from_text(location: str) -> str:
    """Code en fin de libellé, sinon nom de département AURA ; '' si indéterminable."""
    d = dept_from_location(location)
    if d or not location:
        return d
    t = location.lower()
    for ville, code in CITY_DEPT.items():
        if re.search(rf"(?<![\w-]){re.escape(ville)}(?![\w-])", t):
            return code
    # Le plus long d'abord : « haute-savoie » avant « savoie ».
    for nom in sorted(DEPT_BY_NAME, key=len, reverse=True):
        if re.search(rf"(?<![\w-]){re.escape(nom)}(?![\w-])", t):
            return DEPT_BY_NAME[nom]
    return ""


def dept_from_location(location: str) -> str:
    """'Lyon 03 - 69' → '69'. Rend '' si indéterminable (l'appelant décide)."""
    if not location:
        return ""
    m = re.search(r"\b(\d{2}|2[AB])\b\s*$", location.strip())
    if m:
        return m.group(1)
    m = re.search(r"-\s*(\d{2}|2[AB])\b", location)
    return m.group(1) if m else ""


def strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = (s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
          .replace("&gt;", ">").replace("&#39;", "'").replace("&quot;", '"'))
    return re.sub(r"\s+", " ", s).strip()


def format_salary(lo, hi, period: str = "annuel") -> str | None:
    """Libellé de salaire fidèle à la PÉRIODE réellement publiée.

    Ne jamais écrire « annuel » sur un montant mensuel : Adzuna rend le montant
    tel que la source l'a publié (1 867 € = un mois, 46 000 € = une année) et
    seul l'ordre de grandeur les distingue.
    """
    vals = [v for v in (lo, hi) if v]
    if not vals:
        return None
    if period == "annuel" and max(vals) < 10_000:
        period = "mensuel"
    nb = "\u202f"
    fmt = lambda v: f"{int(v):,}".replace(",", nb)
    unit = f"\u20ac brut {period}"
    if len(vals) >= 2 and int(vals[0]) != int(vals[-1]):
        return f"{fmt(vals[0])} \u2013 {fmt(vals[-1])} {unit}"
    return f"{fmt(vals[0])} {unit}"
