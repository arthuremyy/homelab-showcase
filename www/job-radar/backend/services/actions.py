"""
Ce qui demande une action, toutes étapes confondues.

Extrait du routeur pour que le scheduler puisse s'en servir sans dépendre de la
couche HTTP — le récapitulatif quotidien envoyé sur Discord et la vue « À faire »
doivent reposer sur EXACTEMENT les mêmes règles.
"""
import db

# Cadence de relance, en jours. Au-delà de SILENCE_J une candidature est
# probablement sans suite — le cas le plus fréquent, et il mérite d'être nommé
# plutôt que de rester indéfiniment « en cours ».
RELANCE_J = 10
SILENCE_J = 21
DORMANT_J = 7

_BASE = ("SELECT o.id, o.title, o.company, o.location, o.url, o.salary_min, o.salary_max, "
         "o.salary_raw, o.xp_label, o.xp_required, o.is_active, o.last_seen_at, o.posted_at, "
         "s.match_score, p.status, "
         "p.applied_at, p.last_followup_at, p.updated_at AS moved_at "
         "FROM offers o JOIN pipeline p ON p.offer_id=o.id "
         "LEFT JOIN scores s ON s.offer_id=o.id WHERE ")

# Libellés lus tels quels dans l'interface ET sur Discord : une phrase d'action,
# jamais un nom d'étape interne.
GROUPES = [
    ("entretien", "Entretiens en cours",
     "p.status='entretien' ORDER BY p.updated_at ASC"),
    ("relance", f"À relancer (postulé il y a plus de {RELANCE_J} jours)",
     f"p.status='candidate' AND p.applied_at IS NOT NULL "
     f"AND p.applied_at <= datetime('now', '-{RELANCE_J} days') "
     f"AND p.applied_at > datetime('now', '-{SILENCE_J} days') "
     f"AND (p.last_followup_at IS NULL "
     f"     OR p.last_followup_at <= datetime('now', '-{RELANCE_J} days')) "
     f"ORDER BY p.applied_at ASC"),
    ("silence", f"Sans réponse depuis plus de {SILENCE_J} jours : classer ?",
     f"p.status='candidate' AND p.applied_at IS NOT NULL "
     f"AND p.applied_at <= datetime('now', '-{SILENCE_J} days') "
     f"ORDER BY p.applied_at ASC"),
    # Une annonce gardée qui disparaît des sources est probablement pourvue :
    # le dire tout de suite, plutôt que de la laisser dormir dans la liste.
    ("retiree", "Annonces retirées de ta liste « à postuler »",
     "p.status='vivier' AND o.is_active=0 ORDER BY p.updated_at DESC"),
    ("dormant", f"À postuler, en attente depuis plus de {DORMANT_J} jours",
     f"p.status='vivier' AND o.is_active=1 "
     f"AND p.updated_at <= datetime('now', '-{DORMANT_J} days') "
     f"ORDER BY s.match_score DESC"),
]


def groups(limit: int = 40) -> list[dict]:
    """Groupes non vides, lignes brutes — l'appelant décide du formatage."""
    out = []
    with db.connect() as conn:
        for cle, libelle, where in GROUPES:
            items = db.rows(conn.execute(_BASE + where + f" LIMIT {int(limit)}"))
            if items:
                out.append({"key": cle, "label": libelle, "items": items})
    return out
