import { esc } from './fmt.js';

/** Note passagère, avec un bouton d'action facultatif. */
export function toast(message, { action, onAction, ms = 5000, error = false } = {}) {
    const host = document.getElementById('toast-host');
    const el = document.createElement('div');
    el.className = 'toast' + (error ? ' toast-error' : '');
    const span = document.createElement('span');
    span.textContent = message;
    el.append(span);
    if (action && onAction) {
        const b = document.createElement('button');
        b.className = 'btn btn-sm';
        b.textContent = action;
        b.addEventListener('click', () => { el.remove(); onAction(); });
        el.append(b);
    }
    host.append(el);
    requestAnimationFrame(() => el.classList.add('show'));   // le design system masque .toast sans .show
    setTimeout(() => el.remove(), ms);
}

export const fail = (e) => toast(e.message || String(e), { error: true });

/** Fenêtre modale. `body` est du HTML déjà échappé ; `onMount(form)` câble les champs.
 *  Résout FormData à la validation, 'danger' sur le bouton de suppression, null à l'annulation. */
export function modal({ title, body, ok = 'Enregistrer', danger = null, wide = false, onMount }) {
    const host = document.getElementById('modal-host');
    host.innerHTML = `
      <div class="modal-backdrop" data-close>
        <form class="modal${wide ? ' modal-wide' : ''}" role="dialog" aria-modal="true" aria-label="${esc(title)}" novalidate>
          <div class="modal-header"><h3>${esc(title)}</h3>
            <button type="button" class="modal-close" data-close aria-label="Fermer">✕</button></div>
          <div class="modal-body">${body}</div>
          <div class="modal-footer">
            ${danger ? `<button type="button" class="btn btn-danger-outline" data-danger style="margin-right:auto">${esc(danger)}</button>` : ''}
            <button type="button" class="btn" data-close>Annuler</button>
            ${ok ? `<button type="submit" class="btn btn-primary">${esc(ok)}</button>` : ''}
          </div>
        </form>
      </div>`;
    const form = host.querySelector('form');
    onMount?.(form);
    form.querySelector('input:not([type=hidden]), select')?.focus();
    return new Promise((resolve) => {
        const done = (v) => { host.innerHTML = ''; document.removeEventListener('keydown', onKey); resolve(v); };
        const onKey = (e) => { if (e.key === 'Escape') done(null); };
        document.addEventListener('keydown', onKey);
        host.querySelector('.modal-backdrop').addEventListener('click', (e) => {
            if (e.target === e.currentTarget) done(null);
        });
        form.querySelectorAll('button[data-close]').forEach((b) => b.addEventListener('click', () => done(null)));
        form.querySelector('[data-danger]')?.addEventListener('click', () => done('danger'));
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            if (!form.reportValidity()) return;
            done(new FormData(form));
        });
    });
}

/** Bouton occupé pendant une action asynchrone. */
export async function busy(btn, fn) {
    btn.disabled = true;
    try { return await fn(); } finally { btn.disabled = false; }
}
