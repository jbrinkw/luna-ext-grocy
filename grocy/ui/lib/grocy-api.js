/**
 * Grocy API client utilities
 */

const config = require('../config/environment');

/**
 * Fetch from Grocy API
 * @param {string} method - HTTP method
 * @param {string} path - API path
 * @param {object} body - Request body
 * @returns {Promise<any>} Response data
 */
async function grocyFetch(method, path, body) {
  const baseUrl = config.grocy.baseUrl;
  const apiKey = config.grocy.apiKey;
  if (!baseUrl || !apiKey) {
    throw new Error('GROCY_BASE_URL and GROCY_API_KEY are required');
  }
  const url = baseUrl + path;
  const init = {
    method,
    headers: { 'GROCY-API-KEY': apiKey, 'Accept': 'application/json' },
  };
  if (body) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  const res = await fetch(url, init);
  const text = await res.text();
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} - ${text}`);
  try { return JSON.parse(text); } catch { return text; }
}

/**
 * Extract ID from Grocy response
 * @param {any} obj - Response object
 * @returns {number|null} Extracted ID or null
 */
function extractId(obj) {
  try {
    if (obj == null) return null;
    if (typeof obj === 'number') return obj;
    if (typeof obj === 'string' && /^\d+$/.test(obj)) return Number(obj);
    const keys = ['created_object_id', 'id', 'last_inserted_id', 'last_inserted_row_id', 'rowid', 'row_id'];
    for (const k of keys) {
      const v = obj && obj[k];
      if (typeof v === 'number') return v;
      if (typeof v === 'string' && /^\d+$/.test(v)) return Number(v);
    }
  } catch { /* ignore */ }
  return null;
}

module.exports = {
  grocyFetch,
  extractId,
};

