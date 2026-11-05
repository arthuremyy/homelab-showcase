// Client HTTP. Cookie sfauth systématique ; un 401 renvoie au login.
const BASE = '/api/capital/api';

async function request(path, { method = 'GET', body, form } = {}) {
    const opts = { method, credentials: 'include', headers: {} };
    if (form) opts.body = form;
    else if (body !== undefined) {
        opts.headers['Content-Type'] = 'application/json';
        opts.body = JSON.stringify(body);
    }
    const res = await fetch(BASE + path, opts);
    if (res.status === 401) {
        window.location.href = `https://example.com/login.html?redirect=${encodeURIComponent(window.location.href)}`;
        throw new Error('Non authentifié');
    }
    let data = null;
    try { data = await res.json(); } catch { /* réponse sans corps JSON */ }
    if (!res.ok) {
        const detail = data?.errors?.[0]?.msg;
        throw new Error(data?.error || detail || (typeof data?.detail === 'string' ? data.detail : null)
                        || `Erreur HTTP ${res.status}`);
    }
    return data;
}

export const api = {
    get: (p) => request(p),
    post: (p, body = {}) => request(p, { method: 'POST', body }),
    put: (p, body) => request(p, { method: 'PUT', body }),
    del: (p) => request(p, { method: 'DELETE' }),
    upload: (p, form) => request(p, { method: 'POST', form }),
};
