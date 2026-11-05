// Vue d'ensemble : alerte de pointage → total → courbe → comptes → répartition → briefing et alertes (repliés).
import { api } from '../api.js';
import { esc, eur, pct, cls, frDate, CLASS } from '../fmt.js';
import { fail } from '../ui.js';
import { state } from '../state.js';
import { valueChart } from '../chart.js';
import { checkForm, avisForm } from '../forms.js';
import * as secondary from './secondaire.js';

const el = () => document.getElementById('view-ensemble');
let range = '3m';
let points = [];

export const STATE_LABEL = { ok: 'À jour', a_pointer: 'À pointer', ecart: 'Écart' };
export const STATE_BADGE = { ok: 'badge-success', a_pointer: 'badge-warning', ecart: 'badge-danger' };

export function checkLine(acc) {
    const c = acc.check;
    if (!c.date) return 'Jamais pointé';
    const when = c.age_days === 0 ? 'aujourd’hui' : `le ${frDate(c.date)}`;
    return `Pointé ${when}` + (c.state === 'ecart' ? ` — écart de ${eur(c.declared_total - c.computed_total, { sign: true })}` : '');
}

function banner(accounts) {
    const todo = accounts.filter((a) => a.check.state !== 'ok');
    if (!todo.length) return '';
    const danger = todo.some((a) => a.check.state === 'ecart');
    return `<div class="notice ${danger ? 'notice-danger' : 'notice-warning'} banner">
      <span>${todo.map((a) => `<b>${esc(a.name)}</b> ${esc(STATE_LABEL[a.check.state].toLowerCase())}`).join(' · ')}</span>
      <span class="acts">${todo.map((a) => a.id === 'PEE'
          ? `<button class="btn btn-sm" data-avis>Importer un avis PEE</button>`
          : `<button class="btn btn-sm" data-check="${esc(a.id)}">Pointer ${esc(a.name)}</button>`).join('')}</span></div>`;
}

function hero(s) {
    const items = [
        ['Versé', eur(s.total_invested, { round: true }), ''],
        ['Gain', `${eur(s.pnl_eur, { sign: true, round: true })} <small>${esc(pct(s.pnl_pct))}</small>`, cls(s.pnl_eur)],
        ['Aujourd’hui', eur(s.day_change_eur, { sign: true }), cls(s.day_change_eur)],
    ];
    if (s.employer) items.splice(2, 0, ['dont abondement', eur(s.employer, { round: true }), '']);
    return `<div class="card"><div class="card-body hero">
      <div class="hero-main"><span class="kpi-label">Patrimoine investi</span>
        <span class="hero-value">${esc(eur(s.total_value))}</span></div>
      <dl class="hero-side">${items.map(([k, v, c]) => `<div><dt>${esc(k)}</dt><dd class="${c}">${v}</dd></div>`).join('')}</dl>
    </div></div>`;
}

function accountCards(accounts) {
    return `<div class="grid grid-3 accounts">${accounts.map((a) => `
      <button class="card account-card" data-goto="${esc(a.id)}">
        <span class="card-body stack">
          <span class="account-head"><b>${esc(a.name)}</b>
            <span class="badge ${STATE_BADGE[a.check.state]}">${esc(STATE_LABEL[a.check.state])}</span></span>
          <span class="account-value">${esc(eur(a.value))}</span>
          <span class="${cls(a.pnl_eur)}">${esc(eur(a.pnl_eur, { sign: true }))} <small>${esc(pct(a.pnl_pct))}</small></span>
          <span class="sub">${esc(a.provider)} · ${esc(checkLine(a))}</span>
        </span></button>`).join('')}</div>`;
}

function allocation(s) {
    return `<div class="card"><div class="card-header"><h3 class="card-title">Répartition</h3></div>
      <div class="card-body"><ul class="alloc">${s.by_class.map((c) => `<li>
        <span class="grow">${esc(CLASS[c.label] || c.label)}</span><b>${esc(eur(c.value, { round: true }))}</b>
        <span class="dim pct">${esc(c.pct.toLocaleString('fr-FR'))} %</span>
        <div class="meter"><span style="width:${Math.max(c.pct, 0.5)}%"></span></div></li>`).join('')}</ul></div></div>`;
}

function drawChart() {
    const host = document.getElementById('value-chart');
    if (host) valueChart(host, points);
}

async function loadHistory() {
    try {
        points = (await api.get(`/portfolio/history?range=${range}`)).history;
        drawChart();
    } catch (e) { fail(e); }
}

export function render() {
    const s = state.summary;
    if (!s) return;
    el().innerHTML = `
      ${banner(s.accounts)}
      ${hero(s)}
      <div class="card">
        <div class="card-header"><h3 class="card-title">Évolution</h3>
          <ul class="legend inline"><li><i class="sw value"></i>Valeur</li><li><i class="sw invested"></i>Versé</li></ul>
          <div class="segmented" role="group" aria-label="Période">${['1m', '3m', '1y', 'max'].map((r) => `
            <button data-range="${r}" aria-pressed="${r === range}">${{ '1m': '1M', '3m': '3M', '1y': '1A', max: 'Max' }[r]}</button>`).join('')}</div>
        </div>
        <div class="card-body"><div class="chart-host" id="value-chart"></div></div>
      </div>
      ${accountCards(s.accounts)}
      ${allocation(s)}
      <div id="secondary"></div>`;
    loadHistory();
    secondary.render(document.getElementById('secondary'));
}

export function wire() {
    const root = el();
    root.addEventListener('click', (e) => {
        const r = e.target.closest('[data-range]');
        if (r) {
            range = r.dataset.range;
            root.querySelectorAll('[data-range]').forEach((b) => b.setAttribute('aria-pressed', String(b === r)));
            loadHistory();
        }
        const c = e.target.closest('[data-check]');
        if (c) checkForm(c.dataset.check);
        if (e.target.closest('[data-avis]')) avisForm();
    });
    let t;
    window.addEventListener('resize', () => { clearTimeout(t); t = setTimeout(drawChart, 150); });
    secondary.wire(root);
}
