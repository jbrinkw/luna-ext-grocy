/* eslint-disable */
const http = require('http');
const https = require('https');

// Load env from Luna root .env (two levels up from ui/)
try { require('dotenv').config({ path: __dirname + '/../../.env' }); } catch (_) {}

const BASE = (process.env.GROCY_BASE_URL || '').replace(/\/$/, '');
const KEY = process.env.GROCY_API_KEY || '';
const OPENAI_API_KEY = process.env.OPENAI_API_KEY || '';
const NUTRITIONIX_APP_ID = process.env.NUTRITIONIX_APP_ID || 'f2d77be4';
const NUTRITIONIX_APP_KEY = process.env.NUTRITIONIX_APP_KEY || '7442dd236bdc7b6803ad07c39405f388';
const OPENAI_MODEL = process.env.OPENAI_MODEL || 'gpt-4.1';

function step(logs, m) { logs.push(`[step] ${m}`); }
function data(logs, k, v) { try { logs.push(`[data] ${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`); } catch { logs.push(`[data] ${k}: ${String(v)}`); } }

async function grocyFetch(method, path, body) {
  if (!BASE || !KEY) throw new Error('GROCY_BASE_URL and GROCY_API_KEY are required on the server');
  const url = new URL(BASE + path);
  const isHttps = url.protocol === 'https:';
  const dataBuf = body ? Buffer.from(JSON.stringify(body)) : null;
  const opts = {
    method,
    hostname: url.hostname,
    port: url.port || (isHttps ? 443 : 80),
    path: url.pathname + (url.search || ''),
    headers: { 'GROCY-API-KEY': KEY, 'Accept': 'application/json' },
  };
  if (dataBuf) { opts.headers['Content-Type'] = 'application/json'; opts.headers['Content-Length'] = dataBuf.length; }
  const mod = isHttps ? https : http;
  return new Promise((resolve, reject) => {
    const req = mod.request(opts, (res) => {
      let text = '';
      res.on('data', (c) => (text += c.toString()));
      res.on('end', () => {
        if (res.statusCode < 200 || res.statusCode >= 300) return reject(new Error(`${res.statusCode} ${res.statusMessage} - ${text}`));
        try { resolve(JSON.parse(text)); } catch { resolve(text); }
      });
    });
    req.on('error', reject);
    if (dataBuf) req.write(dataBuf);
    req.end();
  });
}

async function fetchNutritionixByUpc(upc) {
  const url = new URL(`https://trackapi.nutritionix.com/v2/search/item?upc=${encodeURIComponent(upc)}`);
  const opts = {
    method: 'GET',
    headers: { 'x-app-id': NUTRITIONIX_APP_ID, 'x-app-key': NUTRITIONIX_APP_KEY, 'Accept': 'application/json' },
  };
  return new Promise((resolve) => {
    https.get(url, opts, (res) => {
      let t=''; res.on('data',(c)=>t+=c); res.on('end',()=>{ try{ const j=JSON.parse(t); resolve(j && Array.isArray(j.foods) && j.foods[0] ? j.foods[0] : null); } catch{ resolve(null); } });
    }).on('error', () => resolve(null));
  });
}

async function aiSuggest(nix) {
  if (!OPENAI_API_KEY) return null;
  try {
    const OpenAI = require('openai');
    const client = new OpenAI.OpenAI({ apiKey: OPENAI_API_KEY });
    const brand = (nix && nix.brand_name) ? String(nix.brand_name).trim() : '';
    const food = (nix && nix.food_name) ? String(nix.food_name).trim() : '';
    const proposed = (brand && food) ? `${brand} ${food}` : (food || brand || 'Nutritionix Item');
    const sys = [
      'You generate: 1) a product name, 2) a storage location label, 3) four due-day defaults.',
      'Return STRICT JSON only: {',
      '  "name": "<final name>",',
      '  "location_label": "fridge|freezer|pantry",',
      '  "default_best_before_days": <int>=0,',
      '  "default_best_before_days_after_open": <int>=0,',
      '  "default_best_before_days_after_freezing": <int>=0,',
      '  "default_best_before_days_after_thawing": <int>=0',
      '}',
      'Rules for name:',
      `- Base name must be "${proposed}" (brand + product).`,
      '- Do NOT change semantics; only fix formatting (spaces/casing/punctuation) if needed.',
    ].join('\n');
    const human = 'Nutritionix JSON follows:\n' + JSON.stringify(nix);
    const resp = await client.chat.completions.create({ model: OPENAI_MODEL, temperature: 0, messages: [ { role: 'system', content: sys }, { role: 'user', content: human } ] });
    const text = resp && resp.choices && resp.choices[0] && resp.choices[0].message && resp.choices[0].message.content || '';
    return JSON.parse(text);
  } catch (_) {
    return null;
  }
}

async function chooseQuantityUnitId() {
  const res = await grocyFetch('GET', '/objects/quantity_units');
  const rows = Array.isArray(res) ? res : (res && res.data) || [];
  let first = null; let best = null;
  for (const r of rows) {
    const id = Number(r && r.id); const nm = String(r && r.name || '').toLowerCase();
    if (!Number.isFinite(id)) continue;
    if (first == null) first = id;
    if (['unit','piece','pcs'].includes(nm)) best = best || id;
  }
  return Number.isFinite(best) ? best : (Number.isFinite(first) ? first : null);
}

async function mapLocationLabelToId(label) {
  const res = await grocyFetch('GET', '/objects/locations');
  const rows = Array.isArray(res) ? res : (res && res.data) || [];
  const lab = String(label || '').toLowerCase();
  for (const r of rows) {
    const id = Number(r && r.id); const nm = String(r && r.name || '').toLowerCase();
    if (!Number.isFinite(id)) continue;
    if (nm === lab || nm.includes(lab)) return id;
  }
  // fallback first id
  for (const r of rows) { const id = Number(r && r.id); if (Number.isFinite(id)) return id; }
  return null;
}

async function mapUserfieldKeys() {
  try {
    const defs = await grocyFetch('GET', '/objects/userfields');
    const rows = Array.isArray(defs) ? defs : (defs && defs.data) || [];
    const desired = {
      'Calories per Serving': ['Calories per Serving','Calories_Per_Serving'],
      'Carbs': ['Carbs'],
      'Fats': ['Fats'],
      'Number of Servings': ['Number of Servings','num_servings'],
      'Protein': ['Protein'],
      'Serving Weight (g)': ['Serving Weight (g)','Serving_Weight'],
    };
    const map = {};
    rows.forEach((r) => {
      if ((r && String((r.entity||r.object_name)||'').toLowerCase()) !== 'products') return;
      const name = String(r && r.name || '');
      const caption = String(r && r.caption || '');
      Object.keys(desired).forEach((label) => {
        if (map[label]) return;
        const aliases = desired[label];
        if (aliases.includes(name) || aliases.includes(caption)) map[label] = name;
      });
    });
    return map;
  } catch {
    return {};
  }
}

async function checkPlaceholderMatch(productName, logs) {
  try {
    step(logs, 'Checking for placeholder product matches ...');
    
    // Get all products
    const allProducts = await grocyFetch('GET', '/objects/products');
    const products = Array.isArray(allProducts) ? allProducts : (allProducts && allProducts.data) || [];
    
    // Filter to placeholders only
    const placeholders = [];
    for (const product of products) {
      try {
        const pid = Number(product.id);
        const name = product.name;
        if (!Number.isFinite(pid) || !name) continue;
        
        // Check if it has placeholder userfield
        const userfields = await grocyFetch('GET', `/userfields/products/${pid}`);
        const isPlaceholder = userfields && (userfields.placeholder === true || userfields.placeholder === 1 || userfields.placeholder === '1');
        
        if (isPlaceholder) {
          placeholders.push({ id: pid, name: name });
        }
      } catch (e) {
        // Skip products that error
        continue;
      }
    }
    
    // If no placeholders, return null
    if (placeholders.length === 0) {
      data(logs, 'placeholder_match.no_placeholders', true);
      return null;
    }
    
    data(logs, 'placeholder_match.found_placeholders', placeholders.length);
    
    // Call OpenAI to match
    return await callOpenAIForMatch(productName, placeholders, logs);
    
  } catch (e) {
    data(logs, 'placeholder_match.exception', String(e));
    return null;
  }
}

async function callOpenAIForMatch(productName, placeholders, logs) {
  try {
    if (!OPENAI_API_KEY) {
      data(logs, 'placeholder_match.no_openai_key', true);
      return null;
    }
    
    const OpenAI = require('openai');
    const client = new OpenAI.OpenAI({ apiKey: OPENAI_API_KEY });
    
    // Build placeholder list
    const placeholderList = placeholders.map(p => `ID ${p.id}: ${p.name}`).join('\n');
    
    const prompt = `Given a product name, determine if it matches one of the placeholder items.
Return the ID of the matching placeholder, or null if no match.

Product name to match: "${productName}"

Placeholder items:
${placeholderList}

Return ONLY a JSON object with this format:
{"matched_product_id": <id or null>}

Match if the product name and placeholder refer to the same product, allowing for minor variations like additional descriptors, sizes, or formatting differences. Return null only if they are genuinely different products.`;
    
    const response = await client.chat.completions.create({
      model: 'gpt-4o-mini',
      messages: [
        { role: 'system', content: 'You are a helpful assistant that matches product names. You respond ONLY with valid JSON.' },
        { role: 'user', content: prompt }
      ],
      response_format: { type: 'json_object' },
      temperature: 0
    });
    
    const content = response.choices[0].message.content;
    const result = JSON.parse(content);
    data(logs, 'placeholder_match.llm_result', result);
    
    const matchedId = result.matched_product_id;
    if (matchedId === null || matchedId === 'null' || matchedId === undefined) {
      return null;
    }
    
    return Number(matchedId);
    
  } catch (e) {
    data(logs, 'placeholder_match.llm_error', String(e));
    return null;
  }
}

async function overridePlaceholder(productId, nixData, barcode, logs) {
  try {
    step(logs, `Overriding placeholder ${productId} with real data ...`);
    
    // Build full name from brand and food_name (same as matching logic)
    const brand = (nixData.brand_name || '').toString().trim();
    const food = (nixData.food_name || '').toString().trim();
    const fullName = (brand && food) ? `${brand} ${food}` : (food || brand || 'Unknown');
    
    // Update product name
    await grocyFetch('PUT', `/objects/products/${productId}`, { name: fullName });
    data(logs, 'placeholder_override.name_updated', fullName);
    
    // Get userfield keys
    const ufMap = await mapUserfieldKeys();
    
    // Update userfields with macro data
    const userfieldUpdates = {};
    if (ufMap['Calories per Serving']) userfieldUpdates[ufMap['Calories per Serving']] = Number(nixData.nf_calories || 0);
    if (ufMap['Carbs']) userfieldUpdates[ufMap['Carbs']] = Number(nixData.nf_total_carbohydrate || 0);
    if (ufMap['Fats']) userfieldUpdates[ufMap['Fats']] = Number(nixData.nf_total_fat || 0);
    if (ufMap['Protein']) userfieldUpdates[ufMap['Protein']] = Number(nixData.nf_protein || 0);
    if (ufMap['Number of Servings']) userfieldUpdates[ufMap['Number of Servings']] = Number(nixData.serving_qty || 1);
    if (ufMap['Serving Weight (g)']) userfieldUpdates[ufMap['Serving Weight (g)']] = Number(nixData.serving_weight_grams || 0);
    userfieldUpdates['placeholder'] = false; // No longer a placeholder
    
    await grocyFetch('PUT', `/userfields/products/${productId}`, userfieldUpdates);
    data(logs, 'placeholder_override.userfields_updated', true);
    
    // Update built-in energy field
    const totalCals = Math.round((Number(nixData.nf_calories || 0)) * (Number(nixData.serving_qty || 1)));
    const energyFields = ['calories', 'energy', 'energy_kcal'];
    for (const field of energyFields) {
      try {
        const payload = {};
        payload[field] = totalCals;
        await grocyFetch('PUT', `/objects/products/${productId}`, payload);
        data(logs, 'placeholder_override.energy_updated', totalCals);
        break;
      } catch (e) {
        // Try next field name
        continue;
      }
    }
    
    // Link barcode to product
    try {
      await grocyFetch('POST', '/objects/product_barcodes', { product_id: productId, barcode });
      data(logs, 'placeholder_override.barcode_linked', true);
    } catch (e) {
      data(logs, 'placeholder_override.barcode_link_error', String(e));
    }
    
    return productId;
    
  } catch (e) {
    data(logs, 'placeholder_override.exception', String(e));
    throw e;
  }
}

async function processAdd(barcode, logs) {
  step(logs, `Operation: add | barcode: ${barcode}`);
  step(logs, 'Checking Grocy for existing product by barcode ...');
  let byb = null;
  try { byb = await grocyFetch('GET', `/stock/products/by-barcode/${barcode}`); } catch (e) { const msg = String(e||''); if (!(msg.includes(' 400 ') || msg.includes(' 404 '))) throw e; }
  if (byb && byb.product && byb.product.id) {
    data(logs, 'grocy.by_barcode.existing', byb);
    step(logs, 'Found existing product; adding amount 1 via /add ...');
    const payload = { amount: 1 };
    try {
      // if product has default bbd, add best_before_date (best-effort)
      const prod = await grocyFetch('GET', `/objects/products/${byb.product.id}`);
      const days = Number(prod && prod.default_best_before_days);
      if (Number.isFinite(days) && days > 0) {
        const d = new Date(); d.setDate(d.getDate() + days);
        const y=d.getFullYear(), m=String(d.getMonth()+1).padStart(2,'0'), dd=String(d.getDate()).padStart(2,'0');
        payload.best_before_date = `${y}-${m}-${dd}`;
      }
    } catch {}
    const r = await grocyFetch('POST', `/stock/products/by-barcode/${barcode}/add`, payload);
    data(logs, 'grocy.add_by_barcode.response', r);
    return { status: 'ok', message: 'Added 1 to existing product by barcode', barcode, operation: 'add', created_product: false, added_amount: 1 };
  }

  step(logs, 'Not found in Grocy; fetching Nutritionix ...');
  const nix = await fetchNutritionixByUpc(barcode);
  if (!nix) throw new Error('Nutritionix had no item for this barcode');
  data(logs, 'nutritionix.item', nix);

  // Check for placeholder match before creating new product
  const brand = (nix.brand_name || '').toString().trim();
  const food = (nix.food_name || '').toString().trim();
  const productNameForMatch = (brand && food) ? `${brand} ${food}` : (food || brand || 'Unknown');
  const placeholderMatch = await checkPlaceholderMatch(productNameForMatch, logs);
  
  if (placeholderMatch && Number.isFinite(placeholderMatch) && placeholderMatch > 0) {
    step(logs, `Matched to placeholder product ${placeholderMatch}; overriding with real data ...`);
    const finalProductId = await overridePlaceholder(placeholderMatch, nix, barcode, logs);
    
    // Add stock for the placeholder product
    step(logs, 'Adding amount 1 to overridden placeholder ...');
    const addPayload = { amount: 1 };
    try {
      // Check if product has default_best_before_days and add best_before_date
      const prod = await grocyFetch('GET', `/objects/products/${finalProductId}`);
      const days = Number(prod && prod.default_best_before_days);
      if (Number.isFinite(days) && days > 0) {
        const d = new Date(); d.setDate(d.getDate() + days);
        const y=d.getFullYear(), m=String(d.getMonth()+1).padStart(2,'0'), dd=String(d.getDate()).padStart(2,'0');
        addPayload.best_before_date = `${y}-${m}-${dd}`;
      }
    } catch {}
    try {
      const add = await grocyFetch('POST', `/stock/products/by-barcode/${barcode}/add`, addPayload);
      data(logs, 'grocy.add_by_barcode.response', add);
    } catch (e) {
      data(logs, 'grocy.add_by_barcode.error', String(e));
    }
    
    return { 
      status: 'ok', 
      message: 'Matched placeholder product and updated with real data', 
      barcode, 
      operation: 'add', 
      created_product: false, 
      matched_placeholder: true,
      added_amount: 1, 
      product_id: finalProductId, 
      product_name: productNameForMatch 
    };
  }

  step(logs, 'No placeholder match; calling AI to generate name, location, due-days ...');
  const ai = await aiSuggest(nix);
  data(logs, 'ai.suggestion', ai || {});
  let name = (ai && ai.name) ? String(ai.name).trim() : productNameForMatch;
  let locLabel = ai && typeof ai.location_label === 'string' ? String(ai.location_label).toLowerCase() : null;
  const due = {
    default_best_before_days: Number(ai && ai.default_best_before_days),
    default_best_before_days_after_open: Number(ai && ai.default_best_before_days_after_open),
    default_best_before_days_after_freezing: Number(ai && ai.default_best_before_days_after_freezing),
    default_best_before_days_after_thawing: Number(ai && ai.default_best_before_days_after_thawing),
  };
  Object.keys(due).forEach(k => { if (!Number.isFinite(due[k]) || due[k] < 0) delete due[k]; });

  const quId = await chooseQuantityUnitId();
  if (!Number.isFinite(quId)) throw new Error('No quantity unit id available');
  const locId = await mapLocationLabelToId(locLabel || 'pantry');
  if (!Number.isFinite(locId)) throw new Error('No location id available');

  step(logs, 'Creating product in Grocy ...');
  const payload = { name, location_id: Number(locId), qu_id_purchase: Number(quId), qu_id_stock: Number(quId), ...due };
  data(logs, 'grocy.create_product.payload', payload);
  const created = await grocyFetch('POST', '/objects/products', payload);
  data(logs, 'grocy.create_product.response', created);
  const product_id = Number((created && (created.created_object_id || created.id)) || 0);
  if (!Number.isFinite(product_id) || product_id <= 0) throw new Error('Product creation did not return an id');

  step(logs, 'Linking barcode to product ...');
  try { await grocyFetch('POST', '/objects/product_barcodes', { product_id, barcode }); } catch (e) { data(logs, 'grocy.link_barcode.error', String(e && e.message || e)); }

  step(logs, 'Mapping and setting userfields ...');
  const ufMap = await mapUserfieldKeys();
  const ufPayload = {};
  const maybe = (label, value) => { const key = ufMap[label]; if (key && typeof value === 'number') ufPayload[key] = value; };
  maybe('Calories per Serving', (typeof nix.nf_calories === 'number') ? nix.nf_calories : Number(nix.nf_calories));
  maybe('Carbs', (typeof nix.nf_total_carbohydrate === 'number') ? nix.nf_total_carbohydrate : Number(nix.nf_total_carbohydrate));
  maybe('Fats', (typeof nix.nf_total_fat === 'number') ? nix.nf_total_fat : Number(nix.nf_total_fat));
  maybe('Number of Servings', (typeof nix.serving_qty === 'number') ? nix.serving_qty : Number(nix.serving_qty));
  maybe('Protein', (typeof nix.nf_protein === 'number') ? nix.nf_protein : Number(nix.nf_protein));
  maybe('Serving Weight (g)', (typeof nix.serving_weight_grams === 'number') ? nix.serving_weight_grams : Number(nix.serving_weight_grams));
  data(logs, 'grocy.userfields.payload', ufPayload);
  if (Object.keys(ufPayload).length > 0) {
    try { await grocyFetch('PUT', `/userfields/products/${product_id}`, ufPayload); } catch (e) { data(logs, 'grocy.userfields.error', String(e && e.message || e)); }
  }

  step(logs, 'Adding amount 1 via by-barcode add ...');
  const addPayload = { amount: 1 };
  if (Number.isFinite(due.default_best_before_days)) {
    try {
      const d = new Date(); d.setDate(d.getDate() + Number(due.default_best_before_days));
      const y=d.getFullYear(), m=String(d.getMonth()+1).padStart(2,'0'), dd=String(d.getDate()).padStart(2,'0');
      addPayload.best_before_date = `${y}-${m}-${dd}`;
    } catch {}
  }
  const add = await grocyFetch('POST', `/stock/products/by-barcode/${barcode}/add`, addPayload);
  data(logs, 'grocy.add_by_barcode.response', add);

  return { status: 'ok', message: 'Created product via Nutritionix+AI and added 1', barcode, operation: 'add', created_product: true, added_amount: 1, product_id, product_name: name };
}

async function processRemove(barcode, logs) {
  step(logs, `Operation: remove | barcode: ${barcode}`);
  step(logs, 'Checking Grocy for existing product by barcode ...');
  let byb = null;
  try { byb = await grocyFetch('GET', `/stock/products/by-barcode/${barcode}`); } catch (e) { const msg = String(e||''); if (!(msg.includes(' 400 ') || msg.includes(' 404 '))) throw e; }
  if (!byb || !byb.product || !byb.product.id) throw new Error('No product exists for this barcode; cannot remove');
  data(logs, 'grocy.by_barcode.existing', byb);
  
  // NOTE: We no longer consume immediately on scan. The frontend will handle the actual
  // consume operation after the user sets the serving amount. This allows fractional
  // consumes (e.g., 1 serving = 0.166 containers when there are 6 servings/container)
  step(logs, 'Product found; frontend will handle consume operation ...');
  
  return { status: 'ok', message: 'Product verified for consume', barcode, operation: 'remove', consumed_amount: 0, product_id: byb.product.id };
}

async function run(op, barcode) {
  const logs = [];
  try {
    if (op === 'add') return await processAdd(barcode, logs);
    if (op === 'remove') return await processRemove(barcode, logs);
    throw new Error('Unknown operation');
  } finally {
    run.lastLogs = logs;
  }
}

module.exports = { run };


