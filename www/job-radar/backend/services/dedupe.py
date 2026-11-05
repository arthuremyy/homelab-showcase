"""
Déduplication inter-sources.

La même offre apparaît sur France Travail et Adzuna sous deux identifiants
différents. La clé de regroupement est un hash de (titre normalisé | entreprise |
ville), sur le même principe de normalisation que providers/news.py de capital-control.
"""
import hashlib
import re

# Mentions de genre et d'habillage qui polluent les intitulés français.
NOISE = re.compile(
    r"\b(f\s*/\s*h|h\s*/\s*f|m\s*/\s*f|f\s*/\s*m|h\s*/\s*f\s*/\s*x|cdi|cdd|"
    r"temps plein|temps partiel|urgent|alternance|stage)\b", re.I)


def norm_text(s: str) -> str:
    s = (s or "").lower()
    s = NOISE.sub(" ", s)
    s = re.sub(r"[^a-z0-9àâäéèêëïîôöùûüÿçœæ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_city(location: str) -> str:
    """'Lyon 03 - 69' → 'lyon 69' : l'arrondissement ne doit pas créer de doublon."""
    s = norm_text(location)
    s = re.sub(r"\b\d{1,2}\b(?!\d)", " ", s, count=1) if re.search(r"\b(lyon|paris|marseille)\b", s) else s
    return re.sub(r"\s+", " ", s).strip()


# Agrégateurs qui republient l'offre d'un tiers sous leur propre nom. Les inclure
# dans la clé de dédup créerait un doublon par agrégateur pour un même poste, donc
# leur nom est neutralisé et le recoupement se fait sur (titre, ville).
AGGREGATORS = {
    "hellowork", "meteojob", "cadremploi", "jobijoba", "monster", "keljob",
    "regionsjob", "pmejob", "tomorrow jobs", "jobteaser", "indeed", "talent io",
    # Boards remontés par Adzuna sous le champ `company` à la place de l'employeur.
    # Termes ENTIERS uniquement : la comparaison est une sous-chaîne, donc un mot
    # générique comme « emploi » fusionnerait à tort des employeurs légitimes.
    "free work", "freework", "direct emploi", "carriere info",
}


def is_aggregator(company: str) -> bool:
    c = norm_text(company)
    return any(a in c for a in AGGREGATORS)


# Sources qui republient l'offre d'un tiers : tout Adzuna est de la republication.
REPUBLISHING_SOURCES = {"adzuna", "jooble"}


def is_republished(offer: dict) -> bool:
    """L'offre vient-elle d'un intermédiaire plutôt que de l'employeur ?"""
    return offer.get("source") in REPUBLISHING_SOURCES or is_aggregator(offer.get("company"))


def compute_loose_hash(offer: dict) -> str:
    """Clé lâche : titre + DÉPARTEMENT, sans l'entreprise ni la ville.

    Le département, et non la ville : chaque source écrit la localité à sa façon
    (« 69 - LYON 03 » chez France Travail, « 1er-Arrondissement, Lyon » ou « Lyon, Rhône »
    chez Adzuna) et une clé basée sur la ville ne recoupe donc jamais deux sources.
    Le code de département, lui, est normalisé par les connecteurs.

    Cette clé ne fusionne QUE si l'un des deux côtés est une republication
    (cf. is_republished) : deux annonces distinctes de même intitulé dans le même
    département, publiées en direct par deux employeurs, restent bien séparées.
    """
    key = "|".join((
        norm_text(offer.get("title"))[:80],
        (offer.get("dept") or "").strip(),
    ))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]


def compute_hash(offer: dict) -> str:
    company = offer.get("company")
    key = "|".join((
        norm_text(offer.get("title"))[:80],
        "" if is_aggregator(company) else norm_text(company)[:50],
        norm_city(offer.get("location"))[:40],
    ))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]
