// « Ce mois » : ce qui peut encore être dépensé, dépenses, prochains fixes, tendance, épargne.
// Ordre de lecture unique (mobile identique) : alerte → chiffre clé → dépenses → fixes → tendance → épargne.
import { api } from '../api.js';
import { esc, eur, monthLabel, shortMonth, shiftMonth, currentMonth } from '../fmt.js';
import { fail, toast, modal } from '../ui.js';
import { state, goto, changed } from '../state.js';

const el = () => document.getElementById('view-mois');
const TOP = 5;              // catégories et fixes visibles avant « voir les autres »
export let last = null;

export function monthNav(month, months) {
    const oldest = months?.length ? months[months.length - 1] : month;
    return `
      <div class="month-nav">
        <button class="btn btn-sm btn-icon" data-month="-1" aria-label="Mois précédent" ${month <= oldest ? 'disabled' : ''}>‹</button>
        <strong>${esc(monthLabel(month))}</strong>
        <button class="btn btn-sm btn-icon" data-month="1" aria-label="Mois suivant" ${month >= currentMonth() ? 'disabled' : ''}>›</button>
      </div>`;
}

export function wireMonthNav(root, rerender) {
    root.addEventListener('click', (e) => {
        const b = e.target.closest('[data-month]');
        if (!b || b.disabled) return;
        state.month = shiftMonth(state.month, Number(b.dataset.month));
        rerender();
    });
}

/** Période en cours : d'un salaire au suivant (repli : mois calendaire). */
const bySalary = (d) => d.period?.by === 'salary';
const shortDate = (iso) => new Date(iso).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' });
const endLabel = (d) => (bySalary(d) ? 'le prochain salaire' : 'la fin du mois');

/** Jours restants dans la période, aujourd'hui compris. */
const daysLeft = (d) => d.period.days - d.period.elapsed + 1;

/** Une seule alerte : la plus grave. */
function banner(d) {
    const b = d.bank;
    if (!b.configured) return `<div class="notice">La banque n’est pas encore reliée. <a href="#/reglages">Voir les réglages</a></div>`;
    if (!b.connected) return `<div class="notice notice-danger">L’accès à la banque a expiré. <a href="#/reglages">Le renouveler</a></div>`;
    if (d.current && d.low && d.low.amount < 0) {
        return `<div class="notice notice-danger">Découvert prévu vers le ${esc(shortDate(d.low.date))} : <b>${eur(d.low.amount)}</b>,
                après les fixes à venir.</div>`;
    }
    if (b.days_left !== null && b.days_left <= 7) {
        return `<div class="notice notice-warning">L’accès à la banque expire dans ${b.days_left} jour(s). <a href="#/reglages">Le renouveler</a></div>`;
    }
    if (d.current && !d.fixed_count && d.suggestions) {
        return `<div class="notice">${d.suggestions} revenus et charges fixes ont été repérés. Valide-les pour obtenir
                ce qui reste à dépenser. <a href="#/fixes">Les valider</a></div>`;
    }
    return '';
}

function side(items) {
    return `<dl class="hero-side">${items.map(([label, value, cls = '', title = '']) => `
      <div${title ? ` title="${esc(title)}"` : ''}><dt>${esc(label)}</dt><dd class="${cls}">${value}</dd></div>`).join('')}</dl>`;
}

/** Mois en cours : ce qui peut encore être dépensé sans découvert ni dépassement. */
function hero(d) {
    const s = d.spendable;
    const balance = ['Solde actuel', eur(d.balance.total), d.balance.total < 0 ? 'neg' : ''];
    const end = [bySalary(d) ? 'Avant le prochain salaire' : 'Fin de mois prévue', eur(d.remaining, { round: true }),
                 d.remaining < 0 ? 'neg' : '', `Solde attendu une fois passés tous les fixes d’ici ${endLabel(d)}`];
    if (!s) {
        return `<div class="card"><div class="card-body hero">
          <div class="hero-main"><div class="kpi-label">Solde actuel</div><div class="hero-value">${eur(d.balance.total)}</div></div>
        </div></div>`;
    }
    let sub, cls = '';
    if (s.amount <= 0) {
        cls = 'neg';
        sub = s.limit === 'solde' ? `découvert prévu vers le ${shortDate(d.low.date)}` : 'reste à vivre déjà dépensé';
    } else {
        if (s.amount < d.low_threshold) cls = 'warn';
        sub = `soit ${eur(s.amount / daysLeft(d), { round: true })} par jour · ${s.limit === 'solde'
            ? `limité par le solde, point bas le ${shortDate(d.low.date)}` : 'limité par le reste à vivre'}`;
    }
    return `
      <div class="card"><div class="card-body hero">
        <div class="hero-main">
          <div class="kpi-label">Dépensable d’ici ${endLabel(d)}${bySalary(d) ? ` <span class="dim">· salaire du ${esc(shortDate(d.period.start))}</span>` : ''}</div>
          <div class="hero-value ${cls}">${eur(s.amount, { round: true })}</div>
          <div class="kpi-sub">${esc(sub)}</div>
        </div>
        ${side([balance, end])}
      </div></div>`;
}

/** Mois passé : ce que le mois a laissé sur le compte. */
function bilan(d) {
    const t = d.totals;
    const r = t.income - t.expenses;
    const sub = t.savings < -0.005 ? `${eur(-t.savings, { round: true })} pris sur l’épargne`
        : t.savings > 0.005 ? `${eur(t.savings, { round: true })} mis de côté` : '';
    return `
      <div class="card"><div class="card-body hero">
        <div class="hero-main">
          <div class="kpi-label">Entrées − dépenses</div>
          <div class="hero-value ${r < 0 ? 'neg' : 'pos'}">${eur(r, { sign: true, round: true })}</div>
          <div class="kpi-sub">${esc(sub)}</div>
        </div>
        ${side([['Entrées', eur(t.income, { round: true }), t.income > 0 ? 'pos' : ''],
                ['Dépenses', eur(t.expenses, { round: true })]])}
      </div></div>`;
}

/** Dépenses courantes (hors fixes) face au reste à vivre, avec le rythme du jour. */
function pace(d) {
    const env = d.envelope;
    const v = Math.max(d.totals.variable, 0);
    if (!env || env <= 0) {
        return `<div class="pace-line"><span>Courantes (hors fixes)</span><b>${eur(v, { round: true })}</b></div>`;
    }
    const day = d.current ? d.period.elapsed : 1;
    const len = d.current ? d.period.days : 1;
    const expected = d.current ? env * day / len : env;
    const over = v > env;
    const ahead = d.current && v > expected;
    const note = over ? `${eur(v - env, { round: true })} au-delà du reste à vivre`
        : !d.current ? `${eur(env - v, { round: true })} non dépensés`
        : ahead ? `${eur(v - expected, { round: true })} au-dessus du rythme du jour`
        : `${eur(expected - v, { round: true })} sous le rythme du jour`;
    return `
      <div class="pace-line"><span>Courantes (hors fixes)</span>
        <b>${eur(v, { round: true })} <span class="dim">/ ${eur(env, { round: true })}</span></b></div>
      <div class="pace" title="Reste à vivre : revenus fixes − charges fixes">
        <div class="meter ${over ? 'is-danger' : ahead ? 'is-warning' : 'is-accent'}"><span style="width:${(Math.min(v / env, 1) * 100).toFixed(1)}%"></span></div>
        ${d.current ? `<i class="pace-mark" style="left:${(day / len * 100).toFixed(1)}%" aria-hidden="true"></i>` : ''}
      </div>
      <div class="kpi-sub ${over ? 'neg' : ahead ? 'warn' : ''}">${esc(note)}</div>`;
}

function catRow(c, max) {
    const ref = c.budget || c.avg;
    const over = ref && c.spent > ref;
    const w = ref ? Math.min(c.spent / ref, 1) : c.spent / max;
    const meter = over ? (c.budget ? 'is-danger' : 'is-warning') : c.budget ? 'is-accent' : '';
    const hint = c.budget ? `/ ${eur(c.budget, { round: true })}` : c.avg ? `habituel ${eur(c.avg, { round: true })}` : '';
    return `
      <li class="cat" data-cat="${esc(c.id ?? '')}" tabindex="0">
        <span class="grow">${esc(c.name)}${c.unsorted ? ' <span class="badge">à classer</span>' : ''}</span>
        <span class="amt">${eur(c.spent, { round: true })}${hint ? ` <span class="dim">${esc(hint)}</span>` : ''}</span>
        <div class="meter ${meter}"><span style="width:${(w * 100).toFixed(1)}%"></span></div>
      </li>`;
}

function spending(d) {
    const cats = d.categories;
    const max = Math.max(...cats.map((c) => c.spent), 1);
    const list = cats.length ? `
      <ul class="cats">${cats.slice(0, TOP).map((c) => catRow(c, max)).join('')}</ul>
      ${cats.length > TOP ? `<details class="more"><summary>${cats.length - TOP} autre${cats.length - TOP > 1 ? 's' : ''} catégorie${cats.length - TOP > 1 ? 's' : ''}</summary>
        <ul class="cats">${cats.slice(TOP).map((c) => catRow(c, max)).join('')}</ul></details>` : ''}
      ${(d.credits || []).map((c) => `
        <div class="credit"><span>${esc(c.name)}</span><b class="pos">${eur(-c.amount, { round: true })}</b></div>`).join('')}`
        : `<p class="dim">Aucune dépense en ${esc(monthLabel(d.month).toLowerCase())}.</p>`;
    return `
      <div class="card">
        <div class="card-header"><span class="card-title">Dépenses${d.current && bySalary(d)
              ? ` <span class="dim">depuis le ${esc(shortDate(d.period.start))}</span>` : ''}</span>
          <div class="card-actions"><b class="num">${eur(d.totals.expenses, { round: true })}</b></div></div>
        <div class="card-body stack">
          <div>${pace(d)}</div>
          ${list}
        </div>
      </div>`;
}

function fixRow(r, bal) {
    return `
      <li class="row">
        <span class="day">${esc(shortDate(r.due))}</span>
        <span class="grow">${esc(r.label)} ${r.missing ? '<span class="badge">absent le mois dernier</span>'
              : r.late ? '<span class="badge badge-warning">en retard</span>' : ''}
          <button type="button" class="link sub" data-link="${r.id}">Déjà passé ? Rattacher l’opération</button></span>
        <b class="${r.amount > 0 ? 'pos' : ''}">${eur(r.amount, { sign: true })}</b>
        <span class="after ${bal < 0 ? 'neg' : ''}">${eur(bal, { round: true })}</span>
      </li>`;
}

/** Fixes à venir dans l'ordre où ils tomberont, avec le solde prévu après chacun
 *  (un fixe en retard est supposé tomber aujourd'hui, comme pour le point bas). */
function upcoming(d) {
    const list = d.pending || [];          // déjà dans l'ordre des échéances
    let bal = d.balance.total ?? 0;
    const rows = list.map((r) => fixRow(r, (bal += r.amount)));
    const inc = list.filter((r) => r.amount > 0).reduce((a, r) => a + r.amount, 0);
    const out = list.filter((r) => r.amount < 0).reduce((a, r) => a + r.amount, 0);
    const body = rows.length ? `
      <ul class="rows fixes-list">
        <li class="row row-head"><span class="day"></span><span class="grow"></span><span>Montant</span><span class="after">Solde après</span></li>
        ${rows.slice(0, TOP).join('')}
      </ul>
      ${rows.length > TOP ? `<details class="more"><summary>${rows.length - TOP} autre${rows.length - TOP > 1 ? 's' : ''} jusqu’au ${esc(shortDate(list[list.length - 1].due))}</summary>
        <ul class="rows fixes-list">${rows.slice(TOP).join('')}</ul></details>` : ''}
      <p class="kpi-sub">À recevoir <b class="pos">${eur(inc, { sign: true, round: true })}</b> · à payer <b>${eur(out, { round: true })}</b></p>`
        : `<p class="dim">${d.suggestions ? 'Aucun fixe confirmé. Des suggestions t’attendent dans Fixes.'
                                          : `Tous les fixes sont passés d’ici ${endLabel(d)}.`}</p>`;
    return `
      <div class="card">
        <div class="card-header"><span class="card-title">Prochains fixes</span>
          <div class="card-actions"><button class="btn btn-sm btn-ghost" data-goto="fixes">Gérer</button></div></div>
        <div class="card-body stack">${body}</div>
      </div>`;
}

/** Entrées et dépenses des 6 derniers mois, avec le résultat de chacun. */
function trend(d) {
    if (d.trend.length < 2) return '';
    const max = Math.max(...d.trend.map((t) => Math.max(t.income, t.expenses)), 1);
    const h = (v) => `${(Math.max(v, 0) / max * 100).toFixed(1)}%`;
    const cur = currentMonth();
    const done = d.trend.filter((t) => t.month !== cur);
    const avg = done.length ? done.reduce((a, t) => a + t.income - t.expenses, 0) / done.length : null;
    return `
      <div class="card">
        <div class="card-header"><span class="card-title">6 derniers mois</span>
          <ul class="legend inline"><li><i style="background:var(--chart-2)"></i>Entrées</li>
            <li><i style="background:var(--chart-4)"></i>Dépenses</li></ul></div>
        <div class="card-body stack">
          <div class="bars">
            ${d.trend.map((t) => {
                const r = t.income - t.expenses;
                return `
              <div class="bar-group ${t.month === cur ? 'is-current' : ''}" title="${esc(monthLabel(t.month))} : ${esc(eur(t.income, { round: true }))} entrées, ${esc(eur(t.expenses, { round: true }))} dépenses${t.month === cur ? ' (en cours)' : ''}">
                <div class="bar-pair">
                  <span style="height:${h(t.income)};background:var(--chart-2)"></span>
                  <span style="height:${h(t.expenses)};background:var(--chart-4)"></span>
                </div>
                <small>${esc(shortMonth(t.month))}</small>
                <small class="net ${r < 0 ? 'neg' : 'pos'}">${eur(r, { sign: true, round: true })}</small>
              </div>`;
            }).join('')}
          </div>
          ${avg !== null ? `<p class="kpi-sub">Entrées − dépenses, moyenne des ${done.length} derniers mois complets :
             <b class="${avg < 0 ? 'neg' : 'pos'}">${eur(avg, { sign: true, round: true })} par mois</b></p>` : ''}
        </div>
      </div>`;
}

function livretCard(d) {
    const l = d.livret;
    if (!l) return '';
    const max = Math.max(...l.series.map((x) => x.balance), 1);
    const n = l.series.length - 1;
    const slope = n > 0 ? (l.series[n].balance - l.series[0].balance) / n : 0;
    return `
      <div class="card">
        <div class="card-header"><span class="card-title">Livret A</span>
          <div class="card-actions"><span class="dim small-inline">estimé</span></div></div>
        <div class="card-body stack">
          ${side([['Solde', eur(l.balance, { round: true })],
                  ['Par mois, en moyenne', eur(slope, { sign: true, round: true }), slope < 0 ? 'neg' : slope > 0 ? 'pos' : '',
                   `Variation moyenne sur ${n} mois`]])}
          <div class="bars short">
            ${l.series.map((x) => `
              <div class="bar-group" title="${esc(monthLabel(x.month))} : ${esc(eur(x.balance, { round: true }))}">
                <div class="bar-pair"><span style="height:${(Math.max(x.balance, 0) / max * 100).toFixed(1)}%;background:var(--chart-2)"></span></div>
                <small>${esc(shortMonth(x.month))}</small>
              </div>`).join('')}
          </div>
        </div>
      </div>`;
}

function overdraftCard(d) {
    const o = d.overdraft;
    if (!o || o.cost <= 0) return '';
    return `
      <div class="card">
        <div class="card-header"><span class="card-title">Découvert</span></div>
        <div class="card-body stack">
          ${side([['Frais sur 12 mois', eur(o.cost), 'neg'],
                  ...(o.days_last_quarter !== null ? [['Dernier trimestre', `${o.days_last_quarter} j à découvert`]] : [])])}
          <p class="dim small">Intérêts débiteurs et commissions d’intervention prélevés par la banque.</p>
        </div>
      </div>`;
}

async function capitalCard() {
    const box = document.getElementById('capital-card');
    if (!box) return;
    try {
        const c = await api.get('/capital');
        if (!c.available) { box.hidden = true; return; }
        const pnl = c.pnl_pct != null ? ` (${c.pnl_pct > 0 ? '+' : ''}${c.pnl_pct.toLocaleString('fr-FR')} %)` : '';
        box.innerHTML = `
          <div class="card-header"><span class="card-title">Investissements</span>
            <div class="card-actions"><a class="btn btn-sm btn-ghost" href="https://capital.example.com/">Ouvrir Capital</a></div></div>
          <div class="card-body stack">
            ${side([['Valeur', eur(c.total_value, { round: true })],
                    ['Plus-value', esc(eur(c.pnl_eur, { sign: true, round: true }) + pnl), (c.pnl_eur ?? 0) >= 0 ? 'pos' : 'neg'],
                    ['Aujourd’hui', eur(c.day_change_eur, { sign: true, round: true })]])}
          </div>`;
        box.hidden = false;
    } catch { box.hidden = true; }
}

export async function render() {
    const root = el();
    let d;
    try { d = await api.post('/overview', { month: state.month }); }
    catch (e) { fail(e); return; }
    last = d;
    document.dispatchEvent(new CustomEvent('overview', { detail: d }));

    root.innerHTML = `
      ${monthNav(d.month, d.months)}
      ${banner(d)}
      ${d.current ? hero(d) : bilan(d)}
      <div class="grid grid-2">
        ${spending(d)}
        ${d.current ? upcoming(d) : trend(d)}
      </div>
      ${d.current ? trend(d) : ''}
      <div class="tiles">
        ${livretCard(d)}
        ${overdraftCard(d)}
        <div class="card" id="capital-card" hidden></div>
      </div>`;
    capitalCard();
}

/** Le fixe n'a pas été reconnu (nouveau libellé, virement sans bénéficiaire) : on désigne
 *  l'opération qui le règle. Le fixe retient ce libellé et, au choix, ce montant. */
async function linkFix(id) {
    const r = (last?.pending || []).find((x) => x.id === id);
    if (!r) return;
    let ops;
    try { ({ operations: ops } = await api.post('/recurring/candidates', { id })); }
    catch (e) { fail(e); return; }
    if (!ops.length) { toast('Aucune opération de ce sens ce mois-ci.'); return; }
    const f = await modal({
        title: `Rattacher ${r.label}`, ok: 'Rattacher',
        body: `
          <div class="field"><label for="l-op">Opération qui règle ce fixe</label>
            <select class="select" id="l-op" name="op_id">${ops.map((o) => `
              <option value="${o.id}">${esc(new Date(o.date).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' }))} · ${
                  esc(o.label)} · ${esc(eur(o.amount, { sign: true }))}${o.status === 'PDNG' ? ' (en attente)' : ''}</option>`).join('')}
            </select></div>
          <label class="check"><input type="checkbox" name="update_amount" checked>
            Retenir ce montant pour les mois suivants (prévu : ${esc(eur(r.amount, { sign: true }))})</label>`,
    });
    if (!f) return;
    try {
        await api.post('/recurring/link', { id, op_id: Number(f.get('op_id')), update_amount: f.has('update_amount') });
        toast(`${r.label} réglé ce mois-ci.`);
        render(); changed();
    } catch (e) { fail(e); }
}

export function wire() {
    const root = el();
    wireMonthNav(root, render);
    root.addEventListener('click', (e) => {
        const l = e.target.closest('[data-link]');
        if (l) { linkFix(Number(l.dataset.link)); return; }
        const c = e.target.closest('[data-cat]');
        if (c) { state.category = c.dataset.cat; goto('operations'); }
    });
    root.addEventListener('keydown', (e) => {
        const c = e.target.closest('[data-cat]');
        if (c && e.key === 'Enter') { state.category = c.dataset.cat; goto('operations'); }
    });
}
