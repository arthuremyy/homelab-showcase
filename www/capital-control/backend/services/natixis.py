"""
Lecture des avis d'opération Natixis Interépargne (PDF).

Page 1 : les versements (montant versé, abondement, date de valorisation, valeur de part, nombre de
parts, date de disponibilité). Les prélèvements sociaux sur l'abondement se déduisent :
versé + abondement − parts × valeur de part.
Page 2 : la situation des avoirs par fonds et par date de disponibilité → sert de pointage.

Le texte extrait d'un PDF n'a pas de mise en page fiable : on repère les lignes par leur
signature (nom, dates, nombres au format français), jamais par leur position.
"""
import io
import re
import unicodedata
from datetime import date

NUM = r"\d{1,3}(?:[   ]\d{3})*,\d+"
DATE = r"\d{2}/\d{2}/\d{4}"
NAME = r"[A-ZÀ-Ý][A-ZÀ-Ý0-9'’ \-\(\)]+?"

# Fonds du plan (relevé « performances et frais ») : nom → code AMF, classe d'actif.
CATALOGUE = {
    "IMPACT ISR EQUILIBRE I": ("QS0004088959", "mixed"),
    "IMPACT ISR DYNAMIQUE I": ("QS0004088942", "equity"),
    "IMPACT ISR PERFORMANCE I": ("QS0004088926", "equity"),
    "IMPACT ISR RENDEMENT SOLIDAIRE (PART I)": ("QS0004088918", "mixed"),
    "EPARGNE ISR MONETAIRE I": ("QS0004088900", "monetary"),
    "AVENIR OBLIGATAIRE I": ("QS0004080857", "bond"),
    "AVENIR RETRAITE 2060-2064 PART I": ("QS0004046130", "equity"),
    "AVENIR RETRAITE 2055-2059 PART I": ("QS0004046122", "equity"),
    "AVENIR RETRAITE 2050-2054 PART I": ("QS0004035323", "equity"),
    "AVENIR RETRAITE 2045-2049 PART I": ("QS0004033559", "equity"),
    "AVENIR RETRAITE 2040-2044 PART I": ("QS0004033104", "equity"),
    "AVENIR RETRAITE 2035-2039 PART I": ("QS0004033542", "equity"),
    "AVENIR RETRAITE 2030-2034 PART I": ("QS0004033096", "mixed"),
    "AVENIR RETRAITE 2025-2029 PART I": ("QS0004033534", "mixed"),
}

MONTHS = {"janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
          "juillet": 7, "août": 8, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11,
          "décembre": 12, "decembre": 12}

RE_OPERATION = re.compile(
    rf"(?P<name>{NAME})\s+(?P<amount>{NUM})\s+(?:(?P<employer>{NUM})\s+)?(?P<valo>{DATE})\s+"
    rf"(?P<price>{NUM})\s+(?P<shares>{NUM})\s+(?P<avail>{DATE}|DISPONIBLE|Disponible)"
    rf"(?:\s*Pr[ée]l[èe]vements sociaux [àa] d[ée]duire\s*-\s*(?P<tax>{NUM}))?")
RE_LOT = re.compile(
    rf"(?P<name>{NAME})\s+(?P<avail>{DATE}|DISPONIBLE|Disponible)\s+(?P<price>{NUM})\s+"
    rf"(?P<shares>{NUM})\s+(?P<value>{NUM})\s+(?P<valo>{DATE})")
RE_SITUATION_DATE = re.compile(r"Situation de vos avoirs au (\d{1,2}) (\w+) (\d{4})", re.I)
RE_RECAP_DATE = re.compile(rf"avoirs\s+au\s+({DATE})", re.I)
# Nature de l'opération (« Abondement » est aussi un en-tête de colonne : jamais une nature).
CATEGORIES = ["Prime de partage de la valeur", "Intéressement", "Participation", "Versement volontaire",
              "Transfert", "Arbitrage", "Remboursement"]


def num(s: str) -> float:
    return float(re.sub(r"[   ]", "", s).replace(",", "."))


def iso(d: str) -> str | None:
    if not re.fullmatch(DATE, d):
        return None                                    # « Disponible »
    dd, mm, yyyy = d.split("/")
    return f"{yyyy}-{mm}-{dd}"


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s.replace("’", "'")).strip().upper()


def pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)


def parse(text: str) -> dict:
    """Texte d'un avis → {operations, lots, situation_date, total, category}."""
    flat = re.sub(r"[ \t]+", " ", text)
    ops = []
    for m in RE_OPERATION.finditer(flat):
        amount, employer = num(m["amount"]), num(m["employer"]) if m["employer"] else 0.0
        price, shares = num(m["price"]), num(m["shares"])
        tax = num(m["tax"]) if m["tax"] else max(round(amount + employer - shares * price, 2), 0.0)
        ops.append({"fund": norm(m["name"]), "amount": amount, "employer_amount": employer,
                    "social_tax": tax, "date": iso(m["valo"]), "price": price, "shares": shares,
                    "available_on": iso(m["avail"])})
    lots = [{"fund": norm(m["name"]), "available_on": iso(m["avail"]), "price": num(m["price"]),
             "shares": num(m["shares"]), "value": num(m["value"]), "date": iso(m["valo"])}
            for m in RE_LOT.finditer(flat)]

    situation = None
    if m := RE_SITUATION_DATE.search(flat):
        month = MONTHS.get(m[2].lower())
        if month:
            situation = date(int(m[3]), month, int(m[1])).isoformat()
    if not situation and (m := RE_RECAP_DATE.search(flat)):
        situation = iso(m[1])
    total = round(sum(lot["value"] for lot in lots), 2) if lots else None
    low = norm(flat)
    category = next((c for c in CATEGORIES if norm(c) in low), "Versement")
    return {"operations": ops, "lots": lots, "situation_date": situation, "total": total,
            "category": category}
