// Test de bout en bout du frontend.
//
// Charge la page RÉELLEMENT servie par le conteneur, exécute son JS dans un DOM,
// et pilote l'interface comme un utilisateur (clavier, clics d'onglet) contre
// l'API réelle derrière nginx.
//
// Il existe parce qu'une simple relecture du code ne suffit pas : une apostrophe
// mal échappée avait empêché le chargement d'un module — donc de tout le
// frontend — sans que rien ne le signale côté serveur.
//
//   cd /tmp && npm install jsdom            # JSDOM_PATH=/tmp/node_modules/jsdom
//   TOKEN=$(docker exec dashboard-api python3 -c "import os,jwt,datetime; \
//     print(jwt.encode({'sub':'admin','exp':datetime.datetime.now(datetime.timezone.utc)+\
//     datetime.timedelta(minutes=20)}, os.getenv('JWT_SECRET'), algorithm='HS256'))")
//   JSDOM_PATH=/tmp/node_modules/jsdom SFAUTH="$TOKEN" node www/job-radar/tests/e2e.mjs
//
// jsdom n'est pas une dépendance du dépôt : il ne sert qu'à ce test, et le
// service n'embarque aucun outillage Node.

// jsdom n'est pas une dépendance du dépôt : JSDOM_PATH permet de pointer une
// installation externe (les modules ES ignorent NODE_PATH).
const pkg = (await import(process.env.JSDOM_PATH || 'jsdom')).default;
const { JSDOM } = pkg;
import https from 'node:https';

const TOKEN = process.env.SFAUTH;
const HOST = 'jobs.example.com', IP = '100.64.0.1';
const agent = new https.Agent({ rejectUnauthorized: false });
const JS = '/srv/homelab/www/job-radar/frontend/assets/js';

function req(path, method = 'GET', payload) {
    const data = payload ? JSON.stringify(payload) : null;
    return new Promise((res, rej) => {
        const r = https.request({
            host: IP, servername: HOST, port: 443, path, method, agent,
            headers: {
                Host: HOST, Cookie: `sfauth=${TOKEN}`,
                ...(data ? { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) } : {}),
            },
        }, (r2) => { let b = ''; r2.on('data', (c) => b += c); r2.on('end', () => res({ status: r2.statusCode, body: b })); });
        r.on('error', rej); if (data) r.write(data); r.end();
    });
}

const page = await req('/');
if (page.status !== 200) { console.log('❌ page HTTP', page.status); process.exit(1); }

const dom = new JSDOM(page.body, { url: `https://${HOST}/`, pretendToBeVisual: true });
const w = dom.window;
const errors = [];

// Expose le DOM en globals : les modules utilisent document/window directement.
globalThis.window = w;
globalThis.document = w.document;
globalThis.history = w.history;
globalThis.KeyboardEvent = w.KeyboardEvent;
globalThis.CustomEvent = w.CustomEvent;

globalThis.fetch = w.fetch = async (input, init = {}) => {
    const r = await req(String(input), init.method || 'GET', init.body ? JSON.parse(init.body) : null);
    return { status: r.status, ok: r.status >= 200 && r.status < 300, json: async () => JSON.parse(r.body) };
};
process.on('unhandledRejection', (e) => errors.push('rejet: ' + (e?.stack || e)));

try { await import(JS + '/main.js'); }
catch (e) { console.log('❌ main.js a échoué au chargement :\n  ' + (e.stack || e)); process.exit(1); }

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
/** Attend qu'une condition devienne vraie — plus fiable qu'un délai fixe. */
async function jusqua(cond, max = 4000) {
    const t0 = Date.now();
    while (Date.now() - t0 < max) { if (cond()) return true; await wait(80); }
    return false;
}
await wait(2500);

const d = w.document, q = (s) => d.querySelector(s);
const check = (ok, label, extra = '') => { console.log(`  ${ok ? '\u2705' : '\u274c'} ${label}${extra ? ' \u2014 ' + extra : ''}`); return ok; };
let fails = 0;
const t = (...a) => { if (!check(...a)) fails++; };

console.log('\u2500\u2500 Chargement \u2500\u2500');
t(errors.length === 0, 'aucune erreur JS', errors.slice(0, 2).join(' | '));
t(!!q('nav.sections button[aria-selected="true"]'), 'onglet actif',
  q('nav.sections button[aria-selected="true"]')?.textContent);

console.log('\u2500\u2500 Aujourd\u2019hui \u2500\u2500');
t(q('nav.sections button[aria-selected="true"]')?.dataset.tab === 'today', 'onglet par d\u00e9faut : Aujourd\u2019hui');
await jusqua(() => q('#today .fresh-card'));
t(!!q('#today .fresh-card'), 'fra\u00eecheur des donn\u00e9es', q('#today .fresh-card .card-title')?.textContent.trim());
t(d.querySelectorAll('#today .fresh-detail tbody tr').length === 3, 'd\u00e9tail des 3 sources');
t(d.querySelectorAll('#today .funnel-step').length === 5, 'entonnoir \u00e0 5 \u00e9tapes',
  [...d.querySelectorAll('#today .funnel-step .kpi-value')].map((x) => x.textContent).join(' \u2192 '));
t(!!(q('#today .todo-card') || q('#today .empty')), '\u00ab \u00c0 faire \u00bb rendu',
  d.querySelectorAll('#today .todo-card').length + ' groupes');
t(!q('#fresh')?.textContent.includes('\u2026') || q('#fresh')?.textContent.includes('Collecte'),
  'indicateur de fra\u00eecheur dans la barre', q('#fresh')?.textContent.trim());
t(!!q('[data-tab="deck"] .pill:not([hidden])'), 'pastille \u00ab \u00c0 trier \u00bb', q('[data-tab="deck"] .pill')?.textContent);

console.log('\u2500\u2500 Trier \u2500\u2500');
q('nav.sections button[data-tab="deck"]').click();
await jusqua(() => q('#stage .folder .sheet'));
const sheet = q('#stage .folder .sheet');
t(!!sheet, 'feuille affich\u00e9e');
t(!!q('#stage .folder .tab'), 'onglet du dossier', q('#stage .folder .tab')?.textContent.trim());
t(d.querySelectorAll('#stage .stamp').length === 2, 'tampons passer/garder pr\u00e9sents');
t(q('#left')?.textContent !== '\u2014', 'compteur', q('#left')?.textContent + ' \u00e0 trier');
t(!q('#decide').hidden, 'actions visibles');
if (sheet) {
    t(!!q('.sheet h2'), 'intitul\u00e9', q('.sheet h2')?.textContent.slice(0, 52));
    t(!!q('.sheet .byline'), 'entreprise et ville', q('.sheet .byline')?.textContent.trim());
    const faits = [...d.querySelectorAll('.sheet > .facts > div')].map((f) =>
        f.querySelector('dt').textContent + ' : ' + f.querySelector('dd').textContent);
    t(faits.length === 3, `socle = 3 faits seulement (${faits.length})`);
    faits.forEach((f) => console.log('       \u00b7 ' + f));
    // Les indices ne doivent PAS \u00eatre sur la face avant : ils vivent dans le d\u00e9pliant.
    const fold = q('.sheet details.fold');
    t(!!fold && !fold.open, 'd\u00e9pliant pr\u00e9sent et ferm\u00e9');
    t(d.querySelectorAll('.gauge').length === 3, 'trois indices, dans le d\u00e9pliant');
}

console.log('\u2500\u2500 Barre commune \u2500\u2500');
// Le th\u00e8me et la navigation viennent de la barre lat\u00e9rale partag\u00e9e (/assets/ui/).
t(!!q('link[href^="/assets/ui/ui.css"]'), 'feuille de style commune');
t(!!q('script[src^="/assets/ui/shell.js"]'), 'barre lat\u00e9rale commune');
t(!q('[data-theme-set]'), 'plus de s\u00e9lecteur de th\u00e8me propre \u00e0 l\u2019application');

console.log('\u2500\u2500 D\u00e9tail (D) \u2500\u2500');
d.body.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'd', bubbles: true }));
await wait(300);
t(q('.sheet details.fold')?.open === true, 'd\u00e9pliant ouvert au clavier');
d.body.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'd', bubbles: true }));
await wait(300);

console.log('\u2500\u2500 Garder (\u2192) \u2500\u2500');
const avant = q('.sheet h2')?.textContent, n0 = q('#left').textContent;
d.body.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
await jusqua(() => q('.sheet h2')?.textContent !== avant);
await jusqua(() => !q('#note')?.hidden);
t(q('.sheet h2')?.textContent !== avant, 'offre suivante', (q('.sheet h2')?.textContent || '').slice(0, 42));
t(q('#left').textContent !== n0, 'compteur d\u00e9cr\u00e9ment\u00e9', `${n0} \u2192 ${q('#left').textContent}`);
t(!q('#note')?.hidden, 'note de confirmation affich\u00e9e', q('#note')?.textContent);
t(!!q('.note-action'), 'annulation propos\u00e9e dans la note');

console.log('\u2500\u2500 Annuler (Z) \u2500\u2500');
q('.note-action')?.click();
await jusqua(() => q('.sheet h2')?.textContent === avant);
t(q('.sheet h2')?.textContent === avant, 'offre restaur\u00e9e depuis la note');

console.log('\u2500\u2500 Liste \u2500\u2500');
q('nav.sections button[data-tab="liste"]').click(); await wait(1600);
t(d.querySelectorAll('#entries .entry').length > 0, 'entr\u00e9es rendues',
  d.querySelectorAll('#entries .entry').length + ' offres');

console.log('\u2500\u2500 Candidatures \u2500\u2500');
q('nav.sections button[data-tab="suivi"]').click();
await jusqua(() => q('#board .bcol'));
t(d.querySelectorAll('#board .bcol').length === 4, 'tableau \u00e0 quatre colonnes',
  [...d.querySelectorAll('#board .bcol-title')].map((x) => x.textContent).join(' | '));
const cartes = d.querySelectorAll('#board .bcard').length;
t(cartes > 0 || !!q('#board .notice'), 'cartes de candidature', cartes + ' cartes');
t(d.querySelectorAll('#board .bcard [data-act]').length > 0 || !cartes, 'action suivante sur chaque carte');
const premiere = q('#board .bcard .btn-primary')?.textContent;
t(!premiere || !/vivier|candidate/.test(premiere), 'libell\u00e9s d\u2019action en clair', premiere);

console.log('\u2500\u2500 R\u00e9glages \u2500\u2500');
q('nav.sections button[data-tab="profil"]').click(); await wait(1600);
t(d.querySelectorAll('#profil .field').length > 0, 'champs',
  d.querySelectorAll('#profil .field').length + ' champs');
t(d.querySelectorAll('.queries li').length > 0, 'recherches par source',
  d.querySelectorAll('.queries li').length + ' requ\u00eates');

if (errors.length) { console.log('\nErreurs JS :'); errors.slice(0, 5).forEach((e) => console.log('   ' + e)); }
console.log(fails ? `\n\u274c ${fails} \u00e9chec(s)` : '\n\u2705 Tout fonctionne');
process.exit(fails ? 1 : 0);
