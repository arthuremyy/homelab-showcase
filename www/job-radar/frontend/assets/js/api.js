// Client HTTP. Cookie sfauth systématique ; un 401 renvoie au login du dashboard.
const BASE = '/api/jobs';

async function request(path, { method = 'GET', body } = {}) {
    const opts = { method, credentials: 'include', headers: {} };
    if (body !== undefined) {
        opts.headers['Content-Type'] = 'application/json';
        opts.body = JSON.stringify(body);
    }
    const res = await fetch(BASE + path, opts);

    if (res.status === 401) {
        window.location.href =
            `https://example.com/login.html?redirect=${encodeURIComponent(window.location.href)}`;
        throw new Error('Non authentifié');
    }
    let data = null;
    try { data = await res.json(); } catch { /* réponse sans corps JSON */ }
    if (!res.ok) throw new Error(data?.error || data?.detail || `Erreur HTTP ${res.status}`);
    return data;
}

export const api = {
    get: (p) => request(p),
    post: (p, body) => request(p, { method: 'POST', body }),
};
