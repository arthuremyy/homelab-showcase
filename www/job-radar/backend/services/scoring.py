"""
Moteur de scoring déterministe — trois indices distincts, tous explicables.

Principe directeur : ne PAS ramener le candidat vers l'industrie. Son passé
GEII/automatisme/production est un levier de CRÉDIBILITÉ (indice de réussite),
jamais un aimant vers les postes OT (indice de matching).

  1. matching     — à quel point l'offre correspond au profil ET à la trajectoire visée
  2. portabilité  — est-ce que ce poste ouvre ou referme des portes à 3-5 ans
  3. réussite     — heuristique de chance de décrocher CE poste (jamais une prédiction)

Chaque indice renvoie (score, breakdown) où breakdown est une liste de
{label, delta} : l'UI affiche les raisons, pas seulement un nombre.
"""
import re
from datetime import datetime, timezone

ENGINE_VERSION = 2

# ── Registres de mots-clés pondérés ──────────────────────────────────────────
# Poids fort : cœur de cible cyber.
CYBER_CORE = {
    "cybersécurité": 10, "cybersecurite": 10, "cyber": 7, "sécurité informatique": 9,
    "soc": 9, "siem": 9, "edr": 8, "xdr": 8, "splunk": 7, "wazuh": 6, "sentinel": 6, "qradar": 6,
    "pentest": 9, "test d'intrusion": 9, "intrusion": 6, "red team": 8, "blue team": 8,
    "forensic": 8, "incident response": 8, "réponse à incident": 8, "cert": 5, "csirt": 8,
    "iso 27001": 8, "27001": 8, "nis2": 8, "ebios": 8, "rgpd": 4, "anssi": 7, "homologation": 6,
    "rssi": 8, "ssi": 7, "grc": 7, "conformité": 4, "analyse de risque": 6,
    "iam": 7, "pki": 6, "authentification": 5, "zero trust": 7, "mfa": 5,
    "vulnérabilité": 7, "vulnerabilite": 7, "durcissement": 6, "hardening": 6,
    "threat": 6, "malware": 6, "phishing": 5, "sécurité cloud": 8, "cloud security": 8,
    "devsecops": 8, "appsec": 7, "owasp": 6,
}

# Poids fort : socle IRC/réseau — transférable partout, c'est sa formation.
INFRA_IRC = {
    "réseau": 5, "reseau": 5, "réseaux": 5, "firewall": 7, "pare-feu": 7, "fortinet": 6,
    "palo alto": 6, "checkpoint": 5, "vpn": 5, "vlan": 5, "segmentation": 6,
    "tcp/ip": 4, "routage": 4, "cisco": 5, "linux": 5, "windows server": 4,
    "active directory": 6, "azure": 5, "aws": 5, "docker": 4, "kubernetes": 5,
    "python": 4, "sql": 3, "supervision réseau": 4, "infrastructure": 3,
}

# Poids MODÉRÉ et jamais déclencheur seul : l'OT ne doit pas tirer le classement.
OT_ICS = {
    "62443": 6, "iec 62443": 6, "scada": 5, "ics": 4, "systèmes industriels": 5,
    "système industriel": 5, "réseau industriel": 5, "purdue": 4, "claroty": 5,
    "nozomi": 5, "cyber vision": 5, "ot": 3, "informatique industrielle": 4,
    "sécurité industrielle": 5,
}

# Contexte sectoriel : rend une offre CYBER plus intéressante (il y est crédible)
# sans la transformer en offre OT.
INDUS_CONTEXT = {
    "industrie": 3, "industriel": 3, "manufacturing": 3, "usine": 3, "production": 2,
    "automobile": 3, "aéronautique": 3, "énergie": 3, "nucléaire": 3, "ferroviaire": 3,
    "transport": 2, "chimie": 2, "pharmaceutique": 2, "agroalimentaire": 2, "logistique": 2,
}

# Marqueurs d'ENFERMEMENT : automatisme/MES à vernis cyber. Détectés surtout dans le titre.
LOCKIN_TITLES = [
    "automaticien", "automatisme", "ingénieur mes", "mes", "gmao", "supervision industrielle",
    "technicien méthodes", "méthodes industrielles", "robotique", "process industriel",
    "informatique industrielle", "chef de projet industriel", "roboticien", "maintenance industrielle",
]
LOCKIN_TEXT = {
    "step7": 4, "tia portal": 4, "siemens s7": 4, "automate programmable": 4, "grafcet": 4,
    "wincc": 4, "profinet": 3, "modbus": 2, "ladder": 4, "schneider unity": 4,
}

# Marqueurs OT dans l'INTITULÉ. Décisifs : ils décrivent le périmètre du POSTE.
# « Ingénieur Cybersécurité Industrielle » est un poste OT, même si « cybersécurité »
# figure dans le titre — c'est justement le cas qu'il ne faut pas laisser remonter.
OT_TITLE_MARKERS = [
    # « ot » seul est indispensable : « Ingénieur CyberSécurité OT » est LE cas à
    # écarter, et il passait à travers quand seuls « ot/it » et « it/ot » figuraient
    # ici. La limite de mot le protège (aucun match dans « robot », « pilote »…).
    "ot", "o.t", "ot/it", "it/ot",
    "industriel", "industrielle", "scada", "ics", "automate",
    "automatisme", "mes", "supervision", "usine", "opérationnelle industrielle",
]

# Compétences réellement transférables → portabilité haute.
PORTABLE = {
    "cloud": 6, "azure": 6, "aws": 6, "gcp": 5, "kubernetes": 6, "docker": 5, "terraform": 5,
    "python": 6, "siem": 6, "splunk": 5, "soc": 6, "pentest": 7, "iso 27001": 6, "nis2": 5,
    "ebios": 5, "devsecops": 6, "ci/cd": 4, "iam": 5, "zero trust": 5, "forensic": 5,
    "cissp": 5, "oscp": 5, "ceh": 3, "giac": 4,
}
# Signaux qui REFERMENT les portes.
NARROWING = {
    "poste unique": 6, "seul informaticien": 10, "seul sur le site": 8, "site unique": 5,
    "logiciel propriétaire": 6, "outil interne": 4, "solution maison": 5, "mono-site": 5,
    "astreinte 24/7": 3, "polyvalent technique": 4,
}

# Intitulés hors métier : commerce, avant-vente, gestion pure. Le mot « cyber » y
# figure (« Ingénieur technico-commercial réseaux & cyber ») mais ce n'est pas un
# poste technique — sans ce garde-fou ils remontent dans le top.
EXCLUDE_ROLE_TITLES = [
    "technico-commercial", "technico commercial", "commercial", "business developer",
    "account manager", "ingénieur d'affaires", "ingenieur d'affaires", "chargé d'affaires",
    "charge d'affaires", "business development", "sales", "vendeur", "customer success",
    "recrutement", "recruteur", "avant-vente", "avant vente",
    # Enseignement : « Un-e intervenant-e pour le module Cybersécurité » sortait à
    # 89/100. Le vocabulaire est celui du métier, le poste n'en est pas un.
    "intervenant", "intervenante", "formateur", "formatrice", "enseignant",
    "enseignante", "professeur", "chargé de cours", "charge de cours",
]

# Certifications exigées qu'il n'a pas (junior) → malus de réussite.
SENIOR_CERTS = ["cissp", "cisa", "cism", "oscp", "iso 27001 lead auditor", "lead implementer", "giac", "gcih"]

# Émetteurs : cabinet de recrutement / intérim → conversion plus faible.
AGENCY_MARKERS = [
    "cabinet de recrutement", "cabinet conseil en recrutement", "recrutement", "adsearch",
    "hays", "michael page", "robert half", "expectra", "randstad", "manpower", "lynx rh",
    "fed it", "page personnel", "approach people", "talents", "recruteur", "intérim", "interim",
    # Agrégateurs / job boards republiant l'offre : l'employeur réel est masqué.
    "cadremploi", "meteojob", "jobijoba", "hellowork", "indeed", "figaro classifieds",
    "talent.io", "jobteaser", "monster", "keljob", "regionsjob",
]
# Grands groupes très sélectifs → malus modéré (beaucoup de candidatures).
PRESTIGE = ["thales", "airbus", "safran", "naval group", "dassault", "google", "amazon",
            "microsoft", "apple", "capgemini", "sopra", "orange cyberdefense", "atos", "accenture"]

AURA_DEPTS = {"01", "03", "07", "15", "26", "38", "42", "43", "63", "69", "73", "74"}

OT_MATCH_CAP = 55        # une offre OT pure ne peut pas dominer le classement
OFFTARGET_CAP = 35
CYBER_MIN = 12           # seuil de "vraie" offre cyber


def _norm(s: str) -> str:
    s = (s or "").lower().replace("\u2019", "'").replace("\u02bc", "'")
    return re.sub(r"\s+", " ", s)


_PAT_CACHE: dict[str, re.Pattern] = {}


def _pat(term: str) -> re.Pattern:
    """Motif sur limites de mots. Indispensable : sans lui « cyber » se déclenche à
    l'intérieur de « cybersécurité » et le score cyber est compté deux fois."""
    p = _PAT_CACHE.get(term)
    if p is None:
        p = _PAT_CACHE[term] = re.compile(rf"(?<!\w){re.escape(term)}(?!\w)")
    return p


def _hits(text: str, registry: dict) -> tuple[int, list[str]]:
    """Somme pondérée des mots-clés trouvés + libellés (chaque terme compté une fois)."""
    total, found = 0, []
    for term, weight in registry.items():
        if _pat(term).search(text):
            total += weight
            found.append(term)
    return total, found


def parse_salary(raw: str) -> tuple[float | None, float | None]:
    """Salaire annuel brut (min, max) à partir du libellé d'une source.

    Trois pièges, tous rencontrés en production :
      * séparateurs de milliers — « 45 000 » et « 45\u202f000 » doivent se relire,
        sinon le regex y voit 45 et 0 et rejette tout ;
      * unités mêlées — Adzuna rend le montant tel que publié : 1 867 € est un
        salaire MENSUEL, 46 000 € un annuel. Rien ne les distingue sauf l'ordre
        de grandeur ;
      * horaire — « 15 € » pour un poste payé à l'heure.
    """
    if not raw:
        return None, None
    t = raw.lower().replace(",", ".")
    # Recolle les milliers : « 45 000 » / « 45\u202f000 » / « 45\u00a0000 » → « 45000 ».
    t = re.sub(r"(\d)[\s\u202f\u00a0](\d{3})\b", r"\1\2", t)
    nums = [float(n) for n in re.findall(r"(\d+(?:\.\d+)?)", t)]
    if not nums:
        return None, None

    if "k" in t:
        nums = [n * 1000 for n in nums]

    hourly = any(w in t for w in ("horaire", "de l'heure", "/h", " heure"))
    monthly = any(w in t for w in ("mensuel", "par mois", "/mois", " mois"))

    # À défaut de mention, l'ordre de grandeur tranche.
    plausible = [n for n in nums if n > 0]
    if plausible and not hourly and not monthly:
        big = max(plausible)
        if big < 200:
            hourly = True
        elif big < 10_000:
            monthly = True

    if hourly:
        nums = [n * 151.67 * 12 for n in nums]     # 35 h/semaine
    elif monthly:
        nums = [n * 12 for n in nums]

    nums = [n for n in nums if 10_000 <= n <= 300_000]
    if not nums:
        return None, None
    return min(nums), max(nums)


def extract_xp_required(text: str) -> int | None:
    """Années d'expérience exigées, si l'offre les annonce."""
    for pat in (r"(\d+)\s*(?:à|-|/)\s*\d+\s*ans?\s+d[e'’]\s*exp",
                r"(?:minimum|mini|au moins|min\.?)\s*(\d+)\s*ans?",
                r"(\d+)\s*ans?\s+(?:minimum|mini|d[e'’]\s*exp[ée]rience)",
                r"exp[ée]rience\s+(?:de\s+)?(\d+)\s*ans?"):
        m = re.search(pat, text)
        if m:
            try:
                v = int(m.group(1))
                if 0 <= v <= 20:
                    return v
            except ValueError:
                pass
    if re.search(r"d[ée]butant|junior|jeune dipl[ôo]m|premi[èe]re exp[ée]rience", text):
        return 0
    return None


def _blob(offer: dict) -> tuple[str, str]:
    """(titre normalisé, texte complet normalisé)."""
    title = _norm(offer.get("title"))
    full = " ".join(_norm(offer.get(f)) for f in ("title", "company", "description", "location"))
    return title, full


# ── 1. Matching ──────────────────────────────────────────────────────────────

def classify(offer: dict) -> tuple[str, dict]:
    """Détermine la famille de l'offre. Retourne (track, signaux)."""
    title, full = _blob(offer)
    cyber, cyber_terms = _hits(full, CYBER_CORE)
    infra, infra_terms = _hits(full, INFRA_IRC)
    ot, ot_terms = _hits(full, OT_ICS)
    ctx, ctx_terms = _hits(full, INDUS_CONTEXT)
    lockin_txt, lockin_terms = _hits(full, LOCKIN_TEXT)
    lockin_title = [m for m in LOCKIN_TITLES if _pat(m).search(title)]

    # Le titre porte l'essentiel du signal : un titre cyber vaut plus qu'un mot perdu dans le corps.
    title_cyber, _ = _hits(title, CYBER_CORE)
    cyber_eff = cyber + title_cyber * 2

    ot_title = [m for m in OT_TITLE_MARKERS if _pat(m).search(title)]
    excl_title = [m for m in EXCLUDE_ROLE_TITLES if _pat(m).search(title)]

    if excl_title:
        # « Ingénieur technico-commercial réseaux & cyber » : vocabulaire cyber,
        # métier commercial. Hors cible, quel que soit le recouvrement de mots-clés.
        track = "hors_cible"
    elif lockin_title or ot_title:
        # L'intitulé dit le périmètre du poste. « Automaticien », « Cybersécurité
        # industrielle », « OT/IT » : c'est de l'industrie, même si le mot cyber
        # est présent. C'est exactement ce qu'on refuse de laisser remonter.
        track = "ot_pur"
    elif cyber_eff >= CYBER_MIN and (ot > 0 or ctx > 0):
        track = "cyber_indus"                  # cible idéale : cyber où son passé est un plus
    elif cyber_eff >= CYBER_MIN:
        track = "cyber_pur"
    elif ot > 0 or lockin_txt > 0:
        track = "ot_pur"
    else:
        track = "hors_cible"

    return track, {
        "cyber": cyber_eff, "infra": infra, "ot": ot, "ctx": ctx,
        "lockin_txt": lockin_txt, "lockin_title": lockin_title, "ot_title": ot_title,
        "excl_title": excl_title,
        "terms": {"cyber": cyber_terms, "infra": infra_terms, "ot": ot_terms,
                  "ctx": ctx_terms, "lockin": lockin_terms + lockin_title},
    }


def score_match(offer: dict, sig: dict, track: str, profile: dict) -> tuple[int, list[dict]]:
    bd: list[dict] = []
    score = 0.0

    # Compétences (0-70). L'OT est plafonné dans sa contribution propre.
    cyber_pts = min(40, sig["cyber"] * 1.4)
    infra_pts = min(20, sig["infra"] * 1.2)
    ot_pts = min(10, sig["ot"] * 0.8)
    if cyber_pts:
        score += cyber_pts
        bd.append({"label": f"Compétences cyber ({', '.join(sig['terms']['cyber'][:5])})", "delta": round(cyber_pts)})
    if infra_pts:
        score += infra_pts
        bd.append({"label": f"Socle réseau/infra ({', '.join(sig['terms']['infra'][:4])})", "delta": round(infra_pts)})
    if ot_pts:
        score += ot_pts
        bd.append({"label": "Compétences OT (contribution volontairement plafonnée)", "delta": round(ot_pts)})

    # Contexte industriel : bonus SEULEMENT si l'offre est déjà cyber.
    if track == "cyber_indus":
        score += 8
        bd.append({"label": "Cyber en contexte industriel — ton passé y est un atout rare", "delta": 8})

    # Géographie
    dept = (offer.get("dept") or "").strip()
    if dept in AURA_DEPTS:
        score += 12
        bd.append({"label": f"Localisation AURA ({offer.get('location')})", "delta": 12})
    elif dept == "INT" or (offer.get("contract_type") == "vie"):
        score += 10
        bd.append({"label": "International / VIE — dans le périmètre visé", "delta": 10})
    elif dept:
        score -= 10
        bd.append({"label": f"Hors périmètre géographique ({offer.get('location')})", "delta": -10})

    # Contrat
    ct = offer.get("contract_type")
    if ct == "cdi":
        score += 8
        bd.append({"label": "CDI", "delta": 8})
    elif ct == "vie":
        score += 7
        bd.append({"label": "VIE", "delta": 7})
    elif ct == "cdd":
        score += 3
        bd.append({"label": "CDD", "delta": 3})
    elif ct in ("alternance", "stage"):
        score -= 30
        bd.append({"label": "Alternance/stage — hors cible (diplômé en 2027)", "delta": -30})

    # Salaire par rapport au plancher du profil.
    # Règle : une offre SANS salaire affiché n'est JAMAIS pénalisée — 44 % des
    # offres cyber n'en publient pas, et ce sont souvent les mieux payées
    # (« à négocier » chez les cabinets). Pénaliser l'absence reviendrait à se
    # priver de la moitié du marché.
    floor = 0.0
    try:
        floor = float(profile.get("salary_floor") or 0)
    except (TypeError, ValueError):
        floor = 0.0
    smin, smax = offer.get("salary_min"), offer.get("salary_max")
    if floor > 0 and smax:
        if smax < floor:
            score -= 18
            bd.append({"label": f"Haut de fourchette ({smax/1000:.0f} k€) sous ton plancher "
                                f"({floor/1000:.0f} k€)", "delta": -18})
        elif smin and smin >= floor * 1.12:
            score += 6
            bd.append({"label": f"Démarre à {smin/1000:.0f} k€, au-dessus de ton plancher", "delta": 6})

    # Séniorité — le champ de la source fait foi ; le regex n'est qu'un repli.
    _, full = _blob(offer)
    xp = offer.get("xp_required")
    if xp is None:
        xp = extract_xp_required(full)
    if xp is not None:
        if xp <= 2:
            score += 10
            label = offer.get("xp_label") or f"{xp} an(s)"
            bd.append({"label": f"Expérience demandée : {label} — accessible", "delta": 10})
        elif xp <= 5:
            score += 2
            bd.append({"label": f"Séniorité demandée ({xp} ans) — tendu mais jouable", "delta": 2})
        else:
            score -= 12
            bd.append({"label": f"Séniorité demandée ({xp} ans) — trop élevée", "delta": -12})

    # Plafonds de trajectoire
    if track == "ot_pur":
        capped = min(score, OT_MATCH_CAP)
        if capped < score:
            bd.append({"label": f"Poste OT/automatisme — score plafonné à {OT_MATCH_CAP} "
                                f"(objectif : ne pas s'enfermer dans l'industrie)",
                       "delta": round(capped - score)})
        score = capped
    elif track == "hors_cible":
        capped = min(score, OFFTARGET_CAP)
        if capped < score:
            reason = (f"Métier hors cible ({', '.join(sig['excl_title'][:2])}) — score plafonné"
                      if sig.get("excl_title") else "Hors cible cyber — score plafonné")
            bd.append({"label": reason, "delta": round(capped - score)})
        score = capped
    elif track == "cyber_pur":
        score *= 0.97

    return max(0, min(100, round(score))), bd


# ── 2. Portabilité de carrière ───────────────────────────────────────────────

def score_portability(offer: dict, sig: dict, track: str) -> tuple[int, list[dict], bool]:
    bd: list[dict] = []
    score = 55.0
    bd.append({"label": "Base", "delta": 55})
    _, full = _blob(offer)

    portable, p_terms = _hits(full, PORTABLE)
    if portable:
        pts = min(30, portable * 1.5)
        score += pts
        bd.append({"label": f"Compétences transférables ailleurs ({', '.join(p_terms[:5])})", "delta": round(pts)})

    narrowing, n_terms = _hits(full, NARROWING)
    if narrowing:
        score -= min(25, narrowing * 1.5)
        bd.append({"label": f"Poste refermant ({', '.join(n_terms[:3])})", "delta": -round(min(25, narrowing * 1.5))})

    lock_in = (bool(sig["lockin_title"]) or bool(sig.get("ot_title"))
               or track == "ot_pur" or sig["lockin_txt"] >= 8)

    if track == "ot_pur":
        score -= 25
        bd.append({"label": "Périmètre OT/automatisme — compétences peu transférables hors industrie", "delta": -25})
    if sig["lockin_title"]:
        score -= 15
        bd.append({"label": f"Intitulé d'automatisme/MES ({', '.join(sig['lockin_title'][:2])})", "delta": -15})
    if sig["lockin_txt"] >= 8:
        score -= 10
        bd.append({"label": f"Stack automate propriétaire ({', '.join(sig['terms']['lockin'][:3])})", "delta": -10})
    if track in ("cyber_pur", "cyber_indus"):
        score += 10
        bd.append({"label": "Poste cyber — compétences recherchées sur tout le marché", "delta": 10})

    return max(0, min(100, round(score))), bd, lock_in


# ── 3. Chance de réussite ────────────────────────────────────────────────────

GHOST_DAYS = 45


def _age_days(first_seen) -> int:
    """Âge en jours depuis la première collecte ; 0 si la date manque ou est illisible."""
    try:
        seen = datetime.fromisoformat(str(first_seen).replace(" ", "T").replace("Z", "+00:00"))
    except ValueError:
        return 0
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - seen).days


def score_success(offer: dict, sig: dict, track: str, profile: dict) -> tuple[int, list[dict]]:
    """Heuristique explicable. C'est ICI, et nulle part ailleurs, que le passé
    industriel joue : il rend le candidat crédible sur TOUTES les offres cyber."""
    bd: list[dict] = []
    score = 50.0
    bd.append({"label": "Base", "delta": 50})
    _, full = _blob(offer)

    # Crédibilité : 4 ans d'alternance en production, pas un stage.
    score += 8
    bd.append({"label": "4 ans d'alternance en production — expérience réelle, pas scolaire", "delta": 8})

    if track == "cyber_indus":
        score += 7
        bd.append({"label": "Cyber en contexte industriel — très peu de candidats parlent les deux langues", "delta": 7})

    # Fraîcheur
    posted = offer.get("posted_at")
    if posted:
        try:
            d = datetime.fromisoformat(posted.replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - d).days
            if age <= 3:
                score += 10
                bd.append({"label": f"Offre publiée il y a {age} j — tu es dans les premiers", "delta": 10})
            elif age <= 10:
                score += 4
                bd.append({"label": f"Offre publiée il y a {age} j", "delta": 4})
            elif age > 21:
                score -= 10
                bd.append({"label": f"Offre publiée il y a {age} j — souvent déjà pourvue", "delta": -10})
        except (ValueError, TypeError):
            pass

    # La source signale un manque de candidats (France Travail
    # offresManqueCandidats). Signal rare et directement exploitable.
    if offer.get("few_candidates"):
        score += 12
        bd.append({"label": "La source signale peu de candidatures sur cette offre", "delta": 12})

    # Écart de séniorité
    xp_req = offer.get("xp_required")
    if xp_req is None:
        xp_req = extract_xp_required(full)
    xp_have = float(profile.get("xp_years") or 4)
    if xp_req is not None and xp_req > 2:
        gap = xp_req - min(xp_have, 2)   # l'alternance ne vaut pas une XP post-diplôme pleine
        score -= min(25, gap * 4)
        bd.append({"label": f"{xp_req} ans demandés, tu sortiras d'école", "delta": -round(min(25, gap * 4))})

    # Certifications senior exigées
    certs = [c for c in SENIOR_CERTS if _pat(c).search(full)]
    if certs:
        score -= 8
        bd.append({"label": f"Certification exigée que tu n'as pas ({', '.join(certs[:2])})", "delta": -8})

    # Nature de l'émetteur
    company = _norm(offer.get("company"))
    if any(m in company for m in AGENCY_MARKERS) or any(m in full[:400] for m in AGENCY_MARKERS[:4]):
        score -= 8
        bd.append({"label": "Cabinet de recrutement / intérim — filtre plus dur qu'un employeur direct", "delta": -8})
    if any(p in company for p in PRESTIGE):
        score -= 6
        bd.append({"label": "Grand groupe très sollicité — forte concurrence", "delta": -6})

    # Offre fantôme : en ligne depuis longtemps (par l'âge : le nombre de passes dépend de la source)
    if _age_days(offer.get("first_seen_at")) > GHOST_DAYS:
        score -= 10
        bd.append({"label": "Offre vue en boucle depuis longtemps — possible offre fantôme", "delta": -10})

    return max(5, min(95, round(score))), bd


def band(score: int) -> str:
    if score >= 75:
        return "excellente"
    if score >= 60:
        return "bonne"
    if score >= 42:
        return "moyenne"
    return "faible"


def score_offer(offer: dict, profile: dict) -> dict:
    """Point d'entrée : calcule les trois indices d'une offre."""
    track, sig = classify(offer)
    match, match_bd = score_match(offer, sig, track, profile)
    port, port_bd, lock_in = score_portability(offer, sig, track)
    succ, succ_bd = score_success(offer, sig, track, profile)
    below_floor = False
    try:
        _f = float(profile.get("salary_floor") or 0)
        below_floor = bool(_f and offer.get("salary_max") and offer["salary_max"] < _f)
    except (TypeError, ValueError):
        pass

    return {
        "track": track,
        "below_floor": int(below_floor),
        "match_score": match, "match_breakdown": match_bd,
        "portability_score": port, "portability_breakdown": port_bd,
        "lock_in_flag": int(lock_in),
        "success_score": succ, "success_breakdown": succ_bd,
        "engine_version": ENGINE_VERSION,
    }
