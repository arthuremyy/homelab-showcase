"""
Libellés bancaires et catégorisation — fonctions PURES (test_budget.py).

La banque ne transmet pas la contrepartie à Enable Banking : on la
lit dans le libellé, dont le format est régulier :

    CARTE X1234 30/09 CAFE DE LA GARE                      paiement carte
    PAIEMENT CARTE DU 01/10 15:06 CAFE CENTRAL               paiement carte en attente
    CARTE X1234 REMBT 18/09 AMAZON PAYMENTS …              remboursement carte
    CARTE X1234 RETRAIT DAB 25/09 17H34 …                  retrait
    CARTE X1234 TRANSF 14/08 Revolut**0000*                transfert carte
    PRELEVEMENT EUROPEEN 91… DE: BOUYGUES TELECOM ID: …    prélèvement
    VIR RECU 91…S DE: ACME EUROPE REF: …                  virement reçu
    000001 VIR INSTANTANE EMIS WERO POUR: X Y IBAN: …      virement émis
    VIREMENT DECLIC SEUIL VERS COMPTE 00000 …              épargne automatique

Ordre de décision de la catégorie :
  1. catégorie posée à la main (category_locked) : jamais recalculée (géré par l'appelant) ;
  2. règle de l'utilisateur sur la contrepartie ;
  3. structure : frais, retrait, épargne (virement vers/depuis soi-même) ;
  4. mot-clé système (db.SEED) sur la contrepartie, le plus long gagne ;
  5. paiement à l'étranger → Voyages ;
  6. virement d'un particulier : reçu → Remboursements reçus, émis → Virements à des proches ;
  7. sinon : Revenus si entrée, Divers si sortie.
Comparaisons par mots entiers, jamais par `in` : « CAF » ne matche pas « CAFE ».
"""
import re
import unicodedata

STOP = {
    "CARTE", "CB", "PRLV", "PRELEVEMENT", "SEPA", "EUROPEEN", "VIR", "VIREMENT", "RECU", "EMIS", "DE",
    "DU", "LA", "LE", "LES", "DES", "A", "AU", "POUR", "ECH", "ID", "EMETTEUR", "MOTIF", "REF", "MDT",
    "FR", "PAIEMENT", "INST", "INSTANTANE", "PERMANENT", "SAS", "SA", "SARL", "EURL", "ET", "PAR",
    "COMMERCE", "ELECTRONIQUE", "INTERNET", "LOGITEL", "WERO", "BQ",
}
TITLES = {"M", "MR", "MME", "MLE", "MLLE", "MM", "MONSIEUR", "MADAME"}
# Une contrepartie contenant l'un de ces mots est une organisation, pas un particulier.
ORG = {"SAS", "SA", "SARL", "EURL", "SCI", "EUROPE", "FRANCE", "GROUP", "GROUPE", "AB", "LTD", "GMBH", "INC",
       "BANK", "BANQUE", "CAF", "CPAM", "URSSAF", "ASSOCIATION", "BDE", "GESTION", "SERVICES", "SERVICE",
       "TELECOM", "ASSURANCE", "ASSURANCES", "MUTUELLE", "TRESOR", "PUBLIC", "DGFIP", "CFAI", "SOCIETE",
       "COMPAGNIE", "CIE", "HOLDING", "INTERNATIONAL", "PAYMENTS", "BETCLIC", "TRUSTLY", "REVOLUT", "LYDIA",
       "PAYPAL", "SUMUP", "STRIPE", "CROUS", "UNIVERSITE", "ECOLE", "INSA", "MAIRIE", "REGION"}
CURRENCIES = {"COP", "USD", "GBP", "CHF", "MXN", "CAD", "JPY", "BRL", "PEN", "ARS", "CLP", "SEK", "NOK", "DKK",
              "PLN", "CZK", "HUF", "MAD", "TND", "THB", "AUD", "TRY"}
COUNTRIES = {"ESPAGNE", "ALLEMAGNE", "AUTRICHE", "ITALIE", "PORTUGAL", "BELGIQUE", "SUISSE", "ESTONIE",
             "COLOMBIE", "MEXIQUE", "ETATS", "UNIS", "ROYAUME", "UNI", "IRLANDE", "PAYS", "BAS", "GRECE",
             "CROATIE", "POLOGNE", "TCHEQUIE", "HONGRIE", "SUEDE", "NORVEGE", "DANEMARK", "MAROC", "TUNISIE",
             "PEROU", "BRESIL", "ARGENTINE", "CHILI", "CANADA", "JAPON", "THAILANDE", "TURQUIE", "LUXEMBOURG",
             "MALTE", "SLOVENIE", "LETTONIE", "LITUANIE", "FINLANDE", "ISLANDE"}

_END = r"(?=\s+(?:REF|MOTIF|ID|IBAN|DATE|CHEZ|NOT PROVIDED)\s*:|\s+REF\b|$)"
PATTERNS = [
    ("withdrawal", re.compile(r"^CARTE X?\d{4}\s+RETRAIT\b")),
    ("card_refund", re.compile(r"^CARTE X?\d{4}\s+REMBT\s+\d{2}/\d{2}\s+(?P<p>.+)")),
    ("card_transfer", re.compile(r"^CARTE X?\d{4}\s+TRANSF\s+\d{2}/\d{2}\s+(?P<p>.+)")),
    ("card", re.compile(r"^CARTE X?\d{4}\s+\d{2}/\d{2}\s+(?P<p>.+)")),
    ("card", re.compile(r"^PAIEMENT CARTE DU \d{2}/\d{2}(?:\s+\d{2}:\d{2})?\s+(?P<p>.+)")),
    ("sweep", re.compile(r"^VIREMENT DECLIC\b")),
    ("debit", re.compile(r"PRELEVEMENT\b.*?\bDE:\s*(?P<p>.+?)" + _END)),
    ("transfer_in", re.compile(r"\bVIR\b.*?\b(?:RECU|RE)\b.*?\bDE:\s*(?P<p>.+?)" + _END)),
    ("transfer_out", re.compile(r"\bVIR\b.*?\bEMIS\b.*?\bPOUR:\s*(?P<p>.+?)" + _END)),
    ("fee", re.compile(r"^(?:INTERETS|COMMISSION|FRAIS|COTIS|COTISATION|AGIOS)\b")),
    ("refund_fee", re.compile(r"^(?:AVANTAGE COMMERCIAL|RETROCESSION|REGULARISATION DE COMMISSION)\b")),
    ("cheque", re.compile(r"^REMISE CHEQUE\b")),
]
OVERDRAFT = re.compile(r"^(?:INTERETS\b.*DEBITEURS|COMMISSION D.INTERVENTION)")


def normalize(text: str) -> str:
    """Majuscules sans accents, ponctuation → espaces, références (mots avec chiffres) retirées."""
    s = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().upper()
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    return " ".join(t for t in s.split() if not any(ch.isdigit() for ch in t))


def _upper(text: str) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().upper()


def _clean_party(raw: str) -> tuple[str, bool]:
    """Contrepartie lisible + drapeau « paiement à l'étranger ».
    S'arrête au premier mot contenant un chiffre (« IMMO GESTION 30 09 BQ ABCD … » → « IMMO GESTION »)."""
    toks = []
    for t in re.split(r"\s+", raw.replace("*", " ").strip()):
        if any(ch.isdigit() for ch in t):
            if toks:
                break
            continue
        toks.append(t)
    words = normalize(" ".join(toks)).split()
    # Devise et pays suivent souvent le montant (« 50,00 USD ETATS UNIS ») : tout le libellé compte.
    foreign = any(w in CURRENCIES or w in COUNTRIES for w in normalize(raw).split())
    # Queue technique : « COMMERCE ELECTRONIQUE », « EUR ESPAGNE », devise.
    while words and (words[-1] in CURRENCIES or words[-1] in COUNTRIES or words[-1] in
                     {"EUR", "COMMERCE", "ELECTRONIQUE", "INTERNET", "D", "DE", "DU"}):
        words.pop()
    return " ".join(words), foreign


def parse_label(label: str) -> dict:
    """{kind, party, foreign, overdraft}. `party` est en majuscules, sans référence."""
    up = re.sub(r"\s+", " ", _upper(label)).strip()
    up_nonum = re.sub(r"^\d+\s+", "", up)
    for kind, rx in PATTERNS:
        m = rx.search(up_nonum)
        if m:
            raw = m.groupdict().get("p")
            party, foreign = _clean_party(raw) if raw else ("", False)
            if kind == "withdrawal":
                party = "RETRAIT DAB"
            elif kind == "sweep":
                party = "EPARGNE AUTOMATIQUE"
            elif not raw:
                party, foreign = _clean_party(up_nonum)
                party = " ".join(party.split()[:4])
            return {"kind": kind, "party": party or up_nonum[:40], "foreign": foreign,
                    "overdraft": bool(OVERDRAFT.search(up_nonum))}
    party, foreign = _clean_party(up_nonum)
    return {"kind": "other", "party": " ".join(party.split()[:5]) or up_nonum[:40],
            "foreign": foreign, "overdraft": False}


def display(party: str) -> str:
    """« IMMO GESTION » → « Immo Gestion » ; « M. ALEX MARTIN » → « Alex Martin »."""
    words = [w for w in party.split() if w not in TITLES]
    return " ".join(w.capitalize() for w in words) or party.title()


def is_person(party: str) -> bool:
    words = party.split()
    if not words or any(w in ORG for w in words):
        return False
    if words[0] in TITLES:
        return True
    return 2 <= len(words) <= 4 and all(w.isalpha() and len(w) > 1 for w in words)


def is_holder(party: str, holder: set[str]) -> bool:
    """Virement vers/depuis soi-même : tous les mots du titulaire sont dans la contrepartie."""
    words = {w for w in party.split() if w not in TITLES}
    return bool(holder) and holder <= words


def key_of(label: str, amount: float | None = None, n: int = 4) -> str:
    """Clé stable d'une contrepartie : premiers mots significatifs (+ sens si montant donné).
    « PRLV SEPA FREE MOBILE ECH/011025 » et « … ECH/011125 » ont la même clé."""
    toks = []
    for t in normalize(label).split():
        if t not in STOP and t not in TITLES and len(t) > 1 and t not in toks:
            toks.append(t)
    k = " ".join(toks[:n])
    if amount is not None:
        k += " +" if amount > 0 else " -"
    return k


def _has_word(hay: str, needle: str) -> bool:
    if not needle:
        return False
    return re.search(r"(?<![A-Z0-9])" + re.escape(needle) + r"(?![A-Z0-9])", hay) is not None


def match(label: str, amount: float, rules: list[dict], keywords: dict[str, list[str]],
          by_name: dict[str, int], holder: set[str] | None = None) -> int | None:
    """Renvoie l'id de catégorie. `rules` : [{pattern, category_id}] ; `keywords` :
    {nom catégorie: [mots-clés]} ; `by_name` : {nom: id} ; `holder` : mots du nom du titulaire."""
    p = parse_label(label)
    party = normalize(p["party"])
    hay = normalize(label)

    best = None
    for r in rules:
        pat = normalize(r["pattern"])
        if (_has_word(party, pat) or _has_word(hay, pat)) and (best is None or len(pat) > len(best[0])):
            best = (pat, r["category_id"])
    if best:
        return best[1]

    def cat(name):
        return by_name.get(name)

    if p["kind"] in ("fee", "refund_fee"):
        return cat("Banque et frais")
    if p["kind"] == "withdrawal":
        return cat("Retraits")
    if p["kind"] == "sweep" or (p["kind"] in ("transfer_in", "transfer_out") and is_holder(party, holder or set())):
        return cat("Épargne et investissement")

    for name, kws in keywords.items():
        cid = by_name.get(name)
        if cid is None:
            continue
        for kw in kws:
            k = normalize(kw)
            if _has_word(party, k) and (best is None or len(k) > len(best[0])):
                best = (k, cid)
    if best:
        return best[1]

    if p["foreign"]:
        return cat("Voyages")
    if p["kind"] in ("transfer_in", "cheque") and is_person(party):
        return cat("Remboursements reçus")
    if p["kind"] == "transfer_out" and is_person(party):
        return cat("Virements à des proches")
    return cat("Revenus" if amount > 0 else "Divers")
