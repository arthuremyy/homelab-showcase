// Tri carte par carte. La carte est une chemise cartonnée : un onglet, la
// feuille, et deux chasses qui dépassent derrière pour dire qu'il en reste.
// On la fait glisser à gauche pour passer, à droite pour garder.
import { api } from '../api.js';
import { esc, SOURCE } from '../fmt.js';
import { note, isTyping } from '../ui.js';
import { renderSheet, lienOffre } from './sheet.js';
import { charger as chargerApercu } from '../apercu.js';

const SEUIL_GESTE = 105;          // px de glissement avant de valider la décision
const ROTATION = 24;              // plus le nombre est grand, moins la carte pivote

const etat = {
    file: [], restant: 0, chargement: false, derniere: null,
    // hide_lock_in n'est plus une case dans la barre de tri : c'est une
    // préférence durable, réglée dans Profil et lue au chargement.
    filtres: { min_match: 40, hide_lock_in: true, sort: 'match', limit: 40 },
};

const scene = () => document.getElementById('stage');
const courante = () => etat.file[0] || null;
const dossier = () => scene().querySelector('.folder');

function peindre() {
    const o = courante();
    document.getElementById('left').textContent = etat.restant || 0;
    document.getElementById('decide').hidden = !o;
    if (!o) {
        scene().innerHTML = `<div class="blank">
            <strong>Tout est trié</strong>
            <p>Plus aucune offre au-dessus de ce seuil de pertinence. Les nouvelles
               arrivent à chaque collecte.</p>
            <button class="btn btn-primary" data-goto="suivi">Voir mes candidatures</button>
            <button class="btn" data-widen>Voir aussi les moins pertinentes</button>
        </div>`;
        document.querySelector('[data-widen]')?.addEventListener('click', () => {
            etat.filtres.min_match = 0;
            document.getElementById('f-seuil').value = '0';
            charger();
        });
        return;
    }

    // Deux chasses au maximum : au-delà l'empilement devient du bruit.
    const chasses = etat.file.slice(1, 3)
        .map((_, i) => `<div class="ghost g${i + 1}"></div>`).reverse().join('');

    scene().innerHTML = `<div class="stack">
        ${chasses}
        <div class="folder">
            <span class="tab"><span>${esc(SOURCE[o.source] || o.source)}</span>
                <span class="ref">Pertinence <b>${esc(o.match_score ?? '—')}</b></span></span>
            <span class="stamp stamp-pass">Pas pour moi</span>
            <span class="stamp stamp-keep">À postuler</span>
            ${renderSheet(o)}
        </div>
    </div>`;
    gestes();
}

async function charger(remiseAZero = true) {
    if (etat.chargement) return;
    etat.chargement = true;
    if (remiseAZero) {
        etat.file = [];
        scene().innerHTML = '<p class="blank">Chargement…</p>';
    }
    try {
        const d = await api.post('/deck', etat.filtres);
        etat.file = d.items || [];
        etat.restant = d.remaining || 0;
    } catch (e) {
        scene().innerHTML = `<p class="blank">${esc(e.message)}</p>`;
        etat.chargement = false;
        return;
    }
    etat.chargement = false;
    peindre();
}

/** Attend la FIN réelle de l'animation. Un délai fixe la coupait avant terme :
 *  la carte ne partait jamais, on ne voyait qu'un basculement de quelques degrés. */
function envoler(sens) {
    const f = dossier();
    if (!f) return Promise.resolve();
    f.classList.remove('settle');
    f.style.transform = '';
    f.classList.add(sens === 'gauche' ? 'out-left' : 'out-right');
    return new Promise((r) => {
        let fini = false;
        const fin = () => { if (!fini) { fini = true; r(); } };
        f.addEventListener('animationend', fin, { once: true });
        setTimeout(fin, 600);                 // filet si l'animation est désactivée
    });
}

async function trancher(statut, sens) {
    const o = courante();
    if (!o) return;
    await envoler(sens);
    etat.file.shift();
    etat.restant = Math.max(0, etat.restant - 1);
    etat.derniere = { offre: o, statut };
    peindre();

    // Confirmation affichée TOUT DE SUITE : la décision est déjà appliquée
    // localement, et attendre la réponse du serveur faisait apparaître
    // l'annulation quand l'utilisateur était déjà passé à la carte suivante.
    note(statut === 'vivier' ? 'Ajoutée à « À postuler »' : 'Écartée', { action: 'Annuler', onAction: annuler });
    try {
        await api.post('/status', { offer_id: o.id, status: statut });
        chargerApercu();                         // pastilles des onglets
    } catch (e) { note(e.message); }

    if (etat.file.length <= 3 && etat.restant > etat.file.length) charger(false);
}

async function annuler() {
    const d = etat.derniere;
    if (!d) return;
    etat.derniere = null;
    try {
        await api.post('/status', { offer_id: d.offre.id, status: 'nouveau' });
        etat.file.unshift(d.offre);
        etat.restant += 1;
        peindre();
        note('Décision annulée');
    } catch (e) { note(e.message); }
}

function ouvrirAnnonce() {
    const o = courante();
    if (o) window.open(lienOffre(o), '_blank', 'noopener,noreferrer');
}

function basculerDetail() {
    const d = scene().querySelector('details.fold');
    if (d) d.open = !d.open;
}

/** Glissement à la souris comme au doigt : la carte suit, pivote, et les
 *  tampons apparaissent progressivement. */
function gestes() {
    const f = dossier();
    if (!f) return;
    const tKeep = f.querySelector('.stamp-keep');
    const tPass = f.querySelector('.stamp-pass');
    let x0 = null, dx = 0, actif = false;

    const bouge = (x) => {
        dx = x - x0;
        f.style.transform = `translateX(${dx}px) rotate(${dx / ROTATION}deg)`;
        const p = Math.min(1, Math.abs(dx) / SEUIL_GESTE);
        tKeep.style.opacity = dx > 12 ? p : 0;
        tPass.style.opacity = dx < -12 ? p : 0;
    };
    const relache = () => {
        if (!actif) return;
        actif = false;
        f.releasePointerCapture?.(f._pid);
        if (Math.abs(dx) >= SEUIL_GESTE) {
            trancher(dx < 0 ? 'ecarte' : 'vivier', dx < 0 ? 'gauche' : 'droite');
            return;
        }
        f.classList.add('settle');                 // rappel élastique
        f.style.transform = '';
        tKeep.style.opacity = 0;
        tPass.style.opacity = 0;
    };

    f.addEventListener('pointerdown', (e) => {
        // Ne pas capturer un clic sur le dépliant, un lien ou un bouton.
        if (e.target.closest('summary, a, button, input, select, textarea')) return;
        actif = true; x0 = e.clientX; dx = 0; f._pid = e.pointerId;
        f.classList.remove('settle');
        f.setPointerCapture?.(e.pointerId);
    });
    f.addEventListener('pointermove', (e) => { if (actif) bouge(e.clientX); });
    f.addEventListener('pointerup', relache);
    f.addEventListener('pointercancel', relache);
}

export function wire() {
    document.getElementById('decide').addEventListener('click', (e) => {
        const b = e.target.closest('[data-do]');
        if (!b) return;
        if (b.dataset.do === 'pass') trancher('ecarte', 'gauche');
        else if (b.dataset.do === 'keep') trancher('vivier', 'droite');
        else ouvrirAnnonce();
    });
    document.getElementById('f-seuil').addEventListener('change', (e) => {
        etat.filtres.min_match = Number(e.target.value); charger();
    });

    document.addEventListener('keydown', (e) => {
        if (!document.getElementById('view-deck').classList.contains('active')) return;
        if (isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey) return;
        const k = e.key.toLowerCase();
        if (e.key === 'ArrowLeft') { e.preventDefault(); trancher('ecarte', 'gauche'); }
        else if (e.key === 'ArrowRight') { e.preventDefault(); trancher('vivier', 'droite'); }
        else if (e.key === 'Enter') { e.preventDefault(); ouvrirAnnonce(); }
        else if (k === 'z') { e.preventDefault(); annuler(); }
        else if (k === 'd') { e.preventDefault(); basculerDetail(); }
    });
}

export const render = async () => {
    try {
        const { profile } = await api.get('/profile');
        etat.filtres.hide_lock_in = profile?.hide_ot !== '0';
    } catch { /* préférence indisponible : on garde le masquage par défaut */ }
    return charger();
};
