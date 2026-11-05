let noteTimer = null;

/** Note passagère. `action` ajoute un bouton dans la note elle-même : c'est là
 *  qu'on regarde au moment où l'on vient d'agir, donc c'est là que l'annulation
 *  a un sens — un bouton permanent dans la barre ne servait à rien. */
export function note(message, { action, onAction, ms = 5000 } = {}) {
    const el = document.getElementById('note');
    el.textContent = '';                      // textContent : aucune injection possible
    el.append(message);
    if (action && onAction) {
        const b = document.createElement('button');
        b.className = 'note-action';
        b.textContent = action;
        b.addEventListener('click', () => { el.hidden = true; onAction(); });
        el.append(b);
    }
    el.hidden = false;
    clearTimeout(noteTimer);
    noteTimer = setTimeout(() => { el.hidden = true; }, ms);
}

export function openDrawer(html) {
    document.getElementById('drawer-body').innerHTML = html;
    document.getElementById('drawer').hidden = false;
    document.getElementById('scrim').hidden = false;
    document.body.style.overflow = 'hidden';
}

export function closeDrawer() {
    document.getElementById('drawer').hidden = true;
    document.getElementById('scrim').hidden = true;
    document.body.style.overflow = '';
}

/** La cible d'un évènement n'est pas toujours un Element (Document, nœud texte…),
 *  auquel cas .matches() n'existe pas. */
export const isTyping = (t) =>
    typeof t?.matches === 'function' && t.matches('input, select, textarea');

export function debounce(fn, ms = 280) {
    let t;
    return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}
