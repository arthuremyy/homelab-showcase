"""
Briefing IA v3 — analyste personnel avec contexte complet.

Entrées : macro élargie (indices, VIX, taux, or, pétrole, Fear & Greed), portefeuille
(positions + stats 52 semaines + perf 1M/3M + indicateurs filtrés par classe), trajectoire
du patrimoine (7j/30j), activité récente (transactions, alertes déclenchées), écarts vs
plafond PEA, et le briefing PRÉCÉDENT pour assurer la continuité.
Modèle : Claude (API Anthropic directe) via ai/llm.py, fallback Gemini.
"""
import json
import logging
from datetime import datetime

import httpx

from ai.llm import ask_json

logger = logging.getLogger("capital.briefing_ai")

# Classes d'actifs pour lesquelles les indicateurs techniques ont un sens
TECHNICALS_CLASSES = {"crypto", "equity", "etf"}


async def get_fear_greed() -> dict | None:
    """Fear & Greed index crypto (alternative.me, gratuit). None si indisponible."""
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get("https://api.alternative.me/fng/?limit=1")
            resp.raise_for_status()
            d = resp.json()["data"][0]
            return {"value": int(d["value"]), "label": d["value_classification"]}
    except Exception:
        return None


def _fmt_indicators(ind: dict) -> str:
    if not ind or "error" in ind:
        return ""
    parts = []
    rsi = ind.get("rsi", {}).get("current")
    if rsi is not None:
        parts.append(f"RSI {rsi:.1f}")
    if ind.get("trend"):
        parts.append(f"tendance {ind['trend']}")
    bb = ind.get("bollinger", {}).get("signal")
    if bb and bb != "neutral":
        parts.append(f"Bollinger {bb}")
    sma20, sma50 = ind.get("sma_20"), ind.get("sma_50")
    price = ind.get("current_price")
    if price and sma20:
        parts.append(f"prix {'>' if price > sma20 else '<'} SMA20")
    if price and sma50:
        parts.append(f"{'>' if price > sma50 else '<'} SMA50")
    return " | ".join(parts)


def _fmt_stats(stats: dict) -> str:
    if not stats:
        return ""
    parts = []
    if stats.get("perf_30d") is not None:
        parts.append(f"1M {stats['perf_30d']:+.1f}%")
    if stats.get("perf_90d") is not None:
        parts.append(f"3M {stats['perf_90d']:+.1f}%")
    if stats.get("pct_from_high") is not None:
        parts.append(f"{stats['pct_from_high']:+.1f}% vs plus-haut 52sem")
    return " | ".join(parts)


def _variation_line(label: str, v: dict | None) -> str | None:
    if not v:
        return None
    return f"{label} : {v['eur']:+.2f}€ ({v['pct']:+.2f}%)"


async def build_briefing(ctx: dict) -> dict:
    """ctx : voir routers/briefing.py::generate_and_store. Retourne {status, briefing}."""
    today = datetime.now().strftime("%d/%m/%Y %H:%M")
    summary = ctx.get("summary", {})
    positions = [p for p in ctx.get("positions", []) if not p.get("closed")]
    indicators = ctx.get("indicators", {})
    asset_stats = ctx.get("asset_stats", {})
    news = ctx.get("news", [])
    fear_greed = ctx.get("fear_greed")
    prev = ctx.get("prev_briefing")
    variations = ctx.get("variations", {})
    recent_txs = ctx.get("recent_txs", [])
    alert_events = ctx.get("alert_events", [])
    pea = ctx.get("pea", {})

    # ── Macro ──
    macro_lines = []
    for label, d in ctx.get("indices", {}).items():
        price, prev_close = d.get("price"), d.get("previous_close")
        if price and prev_close:
            chg = (price - prev_close) / prev_close * 100
            macro_lines.append(f"{label} : {price:,.2f} ({chg:+.2f}%)")
    if fear_greed:
        macro_lines.append(f"Fear & Greed crypto : {fear_greed['value']}/100 ({fear_greed['label']})")

    # ── Portefeuille ──
    traj_lines = [x for x in (
        _variation_line("Variation du jour", {"eur": summary.get("day_change_eur", 0),
                                              "pct": summary.get("day_change_pct", 0)}
                        if summary.get("day_change_eur") is not None else None),
        _variation_line("7 jours", variations.get("7d")),
        _variation_line("30 jours", variations.get("30d")),
    ) if x]

    pos_lines, pos_schema_parts = [], []
    for p in positions:
        line = (f"- {p['name']} ({p['account']}, {p.get('weight_pct', 0)}% du portefeuille) : "
                f"{p['value']:.2f}€ | PRU {p['pru']:.2f}€ → prix {p['price_eur']:.2f}€ | "
                f"P&L {p['pnl_eur']:+.2f}€ ({p['pnl_pct']:+.1f}%) | 24h {p['change_24h']:+.2f}%")
        stats_txt = _fmt_stats(asset_stats.get(p["isin"], {}))
        if stats_txt:
            line += f" | {stats_txt}"
        ind_txt = _fmt_indicators(indicators.get(p["isin"], {}))
        if ind_txt:
            line += f" | {ind_txt}"
        elif p.get("asset_class") == "monetary":
            line += " | fonds monétaire (rendement régulier, pas d'analyse technique pertinente)"
        pos_lines.append(line)
        safe_name = p["name"].replace('"', "'")
        pos_schema_parts.append(
            f'    "{safe_name}": {{"signal": "ACHETER|RENFORCER|CONSERVER|ALLÉGER|VENDRE", '
            f'"commentaire": "lecture factuelle courte", '
            f'"niveau_cle": "niveau de prix ou condition à surveiller (ou null)"}}')

    pos_schema = "{\n" + ",\n".join(pos_schema_parts) if pos_schema_parts else "{"
    pos_schema += ',\n    "synthese": "vision globale du portefeuille en 1-2 phrases"\n  }'

    # ── PEA ──
    pea_line = ""
    if pea.get("plafond"):
        pea_line = (f"PEA : {pea['versements']:.0f}€ versés / {pea['plafond']:.0f}€ "
                    f"({pea['utilisation_pct']:.1f}% du plafond)")

    # ── Activité récente ──
    tx_labels = {"buy": "Achat", "sell": "Vente", "dividend": "Dividende",
                 "deposit": "Dépôt", "withdrawal": "Retrait", "fee": "Frais"}
    tx_lines = [f"- [{t['date']}] {tx_labels.get(t['type'], t['type'])} "
                f"{t.get('name') or t.get('isin') or ''} : {abs(t.get('amount') or 0):.2f}€"
                + (f" ({abs(t.get('shares') or 0):g} parts à {t.get('price', 0):.2f}€)"
                   if t.get("shares") else "")
                for t in recent_txs]
    alert_lines = [f"- [{(e.get('fired_at') or '')[:10]}] {e.get('message', '')}"
                   for e in alert_events]

    # ── Briefing précédent (continuité) ──
    prev_block = "Aucun briefing précédent."
    if prev:
        prev_block = (f"Date : {prev.get('date')}\n"
                      f"Sentiment : {prev.get('sentiment')} ({prev.get('sentiment_score')})\n"
                      f"Résumé : {prev.get('summary', '')}\n"
                      f"Conseil donné : {prev.get('conseil_du_jour', '')}")

    # ── News ──
    news_lines = []
    for a in news[:25]:
        line = f"[{(a.get('published') or '')[:10]}] ({a.get('topic', 'Marché')}) {a.get('title', '')}"
        if a.get("description"):
            line += f" — {a['description'][:160]}"
        line += f" ({a.get('source', '')})"
        news_lines.append(line)

    def block(lines, empty="Rien à signaler"):
        return chr(10).join(lines) if lines else empty

    prompt = f"""Tu es MON analyste financier personnel. Tu suis mon portefeuille jour après jour et tu connais son historique. Date d'analyse : {today}. Langue : français, tutoiement.

RÈGLES ABSOLUES :
1. Tu analyses UNIQUEMENT les données ci-dessous. Aucun événement, chiffre ou actualité inventé. Si une donnée manque, dis-le.
2. Les signaux par position sont des lectures techniques factuelles, pas du conseil en investissement personnalisé.
3. Sois concret et actionnable : cite les chiffres, nomme les niveaux, évite les généralités du type "restez prudent".
4. Assure la CONTINUITÉ avec le briefing précédent : qu'est-ce qui a changé, est-ce que le conseil d'hier tient toujours ?

══════════════ CONTEXTE MACRO ══════════════
{block(macro_lines, "Données non disponibles")}

══════════════ MON PORTEFEUILLE ══════════════
Valeur totale : {summary.get('total_value', 0):.2f}€ | Investi : {summary.get('total_invested', 0):.2f}€
P&L latent : {summary.get('pnl_eur', 0):+.2f}€ ({summary.get('pnl_pct', 0):+.1f}%) | P&L réalisé cumulé : {summary.get('realized_pnl', 0):+.2f}€ | Dividendes cumulés : {summary.get('dividends', 0):.2f}€
{block(traj_lines)}
Répartition par compte : {json.dumps(summary.get('by_account', {}), ensure_ascii=False)}
{pea_line}

Positions :
{block(pos_lines, "Aucune position enregistrée")}

══════════════ MON ACTIVITÉ RÉCENTE (14 jours) ══════════════
Transactions :
{block(tx_lines, "Aucune transaction récente")}
Alertes déclenchées (7 jours) :
{block(alert_lines, "Aucune alerte déclenchée")}

══════════════ BRIEFING PRÉCÉDENT ══════════════
{prev_block}

══════════════ ACTUALITÉS (moins de 7 jours, taguées par sujet) ══════════════
{block(news_lines, "Aucune actualité récente disponible")}

══════════════ INSTRUCTIONS DE SORTIE ══════════════
Calcule sentiment_score entre -100 et 100 à partir des variations pondérées du portefeuille, du contexte macro (VIX, indices) et du ton des actualités.

Génère UNIQUEMENT ce JSON valide (aucun texte avant ou après) :
{{
  "market_sentiment": "bullish|bearish|neutral",
  "sentiment_score": <entier entre -100 et 100>,
  "summary": "4-5 phrases : état des marchés ET de MON portefeuille, à partir des seules données fournies",
  "vs_veille": "1-2 phrases : ce qui a changé depuis le briefing précédent (ou null si premier briefing)",
  "focus_du_jour": "LE point le plus important à surveiller aujourd'hui, en 1 phrase concrète",
  "key_events": ["événement issu des actualités avec sa conséquence pour moi", "...", "..."],
  "risks": ["risque concret identifié dans les données, chiffré si possible", "..."],
  "opportunities": ["opportunité ancrée sur les données", "..."],
  "conseil_du_jour": "conseil concret en 1-2 phrases, cohérent avec le briefing précédent ou expliquant le changement d'avis",
  "portefeuille": {pos_schema}
}}"""

    try:
        briefing, model = await ask_json(prompt)
        briefing["generated_at"] = today
        briefing["generated_by"] = model
        briefing["news_count"] = len(news)
        return {"status": "ok", "briefing": briefing}
    except Exception as e:
        logger.error(f"Briefing LLM error: {e}")
        return {"status": "error", "error": str(e)}
