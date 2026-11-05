import { esc } from './fmt.js';

/** Note passagère, avec un bouton d'action facultatif (ex. « Toujours pour ce libellé »). */
export function toast(message, { action, onAction, ms = 5000, error = false } = {}) {
    const host = document.getElementById('toast-host');
    const el = document.createElement('div');
    el.className = 'toast' + (error ? ' toast-error' : '');
    const span = document.createElement('span');
    span.textContent = message;              // textContent : aucune injection possible
    el.append(span);
    if (action && onAction) {
        const b = document.createElement('button');
        b.className = 'btn btn-sm';
        b.textContent = action;
        b.addEventListener('click', () => { el.remove(); onAction(); });
        el.append(b);
    }
    host.append(el);
    setTimeout(() => el.remove(), ms);
}

export const fail = (e) => toast(e.message || String(e), { error: true });

/** Fenêtre modale. `body` est du HTML déjà échappé. Renvoie une promesse :
 *  FormData à la validation, null à l'annulation. */
export function modal({ title, body, ok = 'Enregistrer', danger = null }) {
    const host = document.getElementById('modal-host');
    host.innerHTML = `
      <div class="modal-backdrop" data-close>
        <form class="modal" role="dialog" aria-modal="true" aria-label="${esc(title)}">
          <div class="modal-header"><h3>${esc(title)}</h3>
            <button type="button" class="modal-close" data-close aria-label="Fermer">✕</button></div>
          <div class="modal-body">${body}</div>
          <div class="modal-footer">
            ${danger ? `<button type="button" class="btn btn-danger-outline" data-danger style="margin-right:auto">${esc(danger)}</button>` : ''}
            <button type="button" class="btn" data-close>Annuler</button>
            <button type="submit" class="btn btn-primary">${esc(ok)}</button>
          </div>
        </form>
      </div>`;
    const form = host.querySelector('form');
    form.querySelector('input, select')?.focus();
    return new Promise((resolve) => {
        const done = (v) => { host.innerHTML = ''; document.removeEventListener('keydown', onKey); resolve(v); };
        const onKey = (e) => { if (e.key === 'Escape') done(null); };
        document.addEventListener('keydown', onKey);
        host.querySelector('.modal-backdrop').addEventListener('click', (e) => {
            if (e.target === e.currentTarget) done(null);
        });
        form.querySelectorAll('button[data-close]').forEach((b) => b.addEventListener('click', () => done(null)));
        form.querySelector('[data-danger]')?.addEventListener('click', () => done('danger'));
        form.addEventListener('submit', (e) => { e.preventDefault(); done(new FormData(form)); });
    });
}

export const confirmBox = (title, text, ok = 'Confirmer') =>
    modal({ title, body: `<p>${esc(text)}</p>`, ok });
