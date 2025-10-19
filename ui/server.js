/* eslint-disable */
/**
 * Grocy Pig Web Server - REFACTORED
 * 
 * Uses modular libraries from:
 * - config/environment.js
 * - lib/grocy-api.js
 * - lib/caches.js
 * - lib/jobs.js
 * - lib/python.js
 * - lib/workers.js
 * - lib/helpers.js
 */

const express = require('express');
const path = require('path');

// Load environment variables from Luna root (two levels up from ui/)
require('dotenv').config({ path: path.join(__dirname, '..', '..', '.env') });

// Import lib modules
const config = require('./config/environment');
const { grocyFetch, extractId } = require('./lib/grocy-api');
const { ensureLocationMap, getLocationMap, getLocationIdToLabel, getUserfieldKeys } = require('./lib/caches');
const {
  enqueueJob: enqueueJobLib,
  getJob,
  updateJob,
  addJobLog,
  getRecentNewItems,
  addRecentNewItem,
  updateRecentNewItem,
  getModificationLogs,
  addModificationLog,
  isWorkerActive,
  setWorkerActive,
  getNextJob,
} = require('./lib/jobs');
const { spawnPythonTool, spawnPythonScript, spawnPythonScraper } = require('./lib/python');
const { processWithWorkerPool } = require('./lib/workers');
const { cleanWalmartUrl, findLastJson, findLastData } = require('./lib/helpers');

// Load processor
const processor = require('./processor');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

// Debug: Log environment
console.log('Debug - Environment variables:');
console.log('GROCY_BASE_URL:', config.grocy.baseUrl ? 'SET' : 'NOT SET');
console.log('GROCY_API_KEY:', config.grocy.apiKey ? 'SET' : 'NOT SET');
console.log('OPENAI_API_KEY:', config.openai.apiKey ? 'SET' : 'NOT SET');

// Initialize location cache
let locationMap, locationIdToLabel;
ensureLocationMap().then(() => {
  locationMap = getLocationMap();
  locationIdToLabel = getLocationIdToLabel();
});

// Userfield cache (loaded on-demand via getUserfieldKeys)
let userfieldKeyCache = null;

// Legacy compatibility wrappers for functions used in routes
async function mapUserfieldKeys() {
  if (userfieldKeyCache) return userfieldKeyCache;
  userfieldKeyCache = await getUserfieldKeys();
  return userfieldKeyCache;
}

async function getServingsKey() {
  const map = await mapUserfieldKeys();
  return map && map.servings;
}

// Keep product helpers that are called by routes
async function getProduct(pid) {
  try { return await grocyFetch('GET', `/objects/products/${Number(pid)}`); } catch { return null; }
}

async function resolveServingsQuId() {
  try {
    const res = await grocyFetch('GET', '/objects/quantity_units');
    const rows = Array.isArray(res) ? res : (res && res.data) || [];
    let firstId = null;
    for (const r of rows) {
      const id = Number(r && r.id);
      const name = String(r && r.name || '').toLowerCase();
      if (!Number.isFinite(id)) continue;
      if (firstId == null) firstId = id;
      if (['serving','servings','portion','portions'].some(w => name.includes(w))) return id;
    }
    const created = await grocyFetch('POST', '/objects/quantity_units', { name: 'Serving', name_plural: 'Servings' });
    const cid = extractId(created);
    return Number.isFinite(cid) ? Number(cid) : (Number.isFinite(firstId) ? Number(firstId) : null);
  } catch (_) { return null; }
}

async function findProductConversionId(pid, fromQuId, toQuId) {
  try {
    const data = await grocyFetch('GET', '/objects/quantity_unit_conversions');
    const rows = Array.isArray(data) ? data : (data && data.data) || [];
    for (const r of rows) {
      if (Number(r && r.product_id) === Number(pid) && Number(r && r.from_qu_id) === Number(fromQuId) && Number(r && r.to_qu_id) === Number(toQuId)) {
        const id = Number(r && r.id);
        if (Number.isFinite(id)) return id;
      }
    }
  } catch (_) {}
  return null;
}

async function createOrUpdateConversion(pid, fromQuId, toQuId, factor) {
  const payload = { product_id: Number(pid), from_qu_id: Number(fromQuId), to_qu_id: Number(toQuId), factor: Number(factor) };
  const existingId = await findProductConversionId(pid, fromQuId, toQuId);
  if (Number.isFinite(existingId)) {
    return await grocyFetch('PUT', `/objects/quantity_unit_conversions/${existingId}`, payload);
  }
  try {
    return await grocyFetch('POST', '/objects/quantity_unit_conversions', payload);
  } catch (e) {
    const id = await findProductConversionId(pid, fromQuId, toQuId);
    if (Number.isFinite(id)) return await grocyFetch('PUT', `/objects/quantity_unit_conversions/${id}`, payload);
    throw e;
  }
}

async function ensureProductServingsConversion(pid, factor) {
  const prod = await getProduct(pid);
  if (!prod) return;
  const fromQuId = Number(prod && prod.qu_id_stock);
  if (!Number.isFinite(fromQuId)) return;
  const toQuId = await resolveServingsQuId();
  if (!Number.isFinite(toQuId)) return;
  const f = Number(factor);
  if (!Number.isFinite(f) || f <= 0) return;
  try { await createOrUpdateConversion(pid, fromQuId, toQuId, f); } catch (_) {}
}

async function updateProductEnergyFromUserfields(pid) {
  try {
    const pidNum = Number(pid);
    if (!Number.isFinite(pidNum)) return;
    const ufMap = await mapUserfieldKeys();
    const cpsKey = ufMap && ufMap['Calories per Serving'];
    const nservKey = ufMap && ufMap['Number of Servings'];
    if (!cpsKey || !nservKey) return;
    const ufs = await grocyFetch('GET', `/userfields/products/${pidNum}`);
    const cps = Number(ufs && ufs[cpsKey]);
    const nserv = Number(ufs && ufs[nservKey]);
    if (!Number.isFinite(cps) || cps <= 0 || !Number.isFinite(nserv) || nserv <= 0) return;
    const total = Math.round(cps * nserv);
    const candidates = ['calories', 'energy', 'energy_kcal'];
    for (const field of candidates) {
      try {
        const payload = {}; payload[field] = Number(total);
        await grocyFetch('PUT', `/objects/products/${pidNum}`, payload);
        return;
      } catch (_) {}
    }
  } catch (_) {}
}

async function getProductSummaryByBarcode(barcode) {
  try {
    const byb = await grocyFetch('GET', `/stock/products/by-barcode/${encodeURIComponent(barcode)}`);
    if (!byb || !byb.product || !byb.product.id) return { exists: false };
    const product_id = Number(byb.product.id);
    const name = String(byb.product.name || '').trim();
    return { exists: true, product_id, name };
  } catch (_) {
    return { exists: false };
  }
}

// Walmart price update jobs (in-memory)
const priceUpdateJobs = new Map();
let priceUpdateJobId = 1;

// Wrapper for enqueueJob to match original signature
function enqueueJob(op, barcode) {
  const id = enqueueJobLib({ op, barcode });
  return { id };
}

// Helper for running local processor
async function runLocalProcessor(op, barcode, jobId) {
  try {
    const result = await processor.processBarcode(op, barcode, {
      onLog: (msg) => addJobLog(jobId, msg),
      onRecentItem: (item) => addRecentNewItem(item),
    });
    return result;
  } catch (error) {
    throw error;
  }
}

// Helper for Python job execution
async function runPythonJob(jobId) {
  const job = getJob(jobId);
  if (!job) return;
  
  try {
    const result = await spawnPythonScript('processor.py', job.op, job.barcode);
    const parsed = findLastData(result);
    return parsed || { success: false, error: 'No result from Python processor' };
  } catch (error) {
    return { success: false, error: error.message };
  }
}

// ============================================================================
// ROUTES START HERE
// ============================================================================

app.post('/api/scan/add', (req, res) => {
  const barcode = String(req.body && req.body.barcode || '').trim();
  if (!barcode) return res.status(400).json({ error: 'barcode required' });
  const job = enqueueJob('add', barcode);
  res.json({ jobId: job.id });
});

app.post('/api/scan/remove', (req, res) => {
  const barcode = String(req.body && req.body.barcode || '').trim();
  if (!barcode) return res.status(400).json({ error: 'barcode required' });
  const job = enqueueJob('remove', barcode);
  res.json({ jobId: job.id });
});

app.get('/api/jobs/:id', (req, res) => {
  const job = jobStore.get(String(req.params.id));
  if (!job) return res.status(404).json({ error: 'not found' });
  // Light logs: only keep [step] lines and the final JSON result
  const minimalLogs = (job.logs || []).filter((l) => l && l.startsWith('[step] '));
  res.json({ id: job.id, status: job.status, logs: minimalLogs, result: job.result });
});

// Product summary by barcode (id, name)
app.get('/api/products/summary/by-barcode/:barcode', async (req, res) => {
  try {
    const barcode = String(req.params.barcode || '').trim();
    if (!barcode) return res.status(400).json({ error: 'barcode required' });
    const summary = await getProductSummaryByBarcode(barcode);
    res.json(summary);
  } catch (e) {
    res.status(400).json({ error: String(e && e.message || e) });
  }
});

// Get/Set Number of Servings userfield
app.get('/api/products/:productId/servings', async (req, res) => {
  try {
    const pid = Number(req.params.productId);
    if (!Number.isFinite(pid)) return res.status(400).json({ error: 'invalid productId' });
    const key = await getServingsKey();
    console.log(`[GET /api/products/${pid}/servings] Key: "${key}"`);
    if (!key) return res.json({ servings: null });
    const ufs = await grocyFetch('GET', `/userfields/products/${pid}`);
    console.log(`[GET /api/products/${pid}/servings] Userfields:`, ufs);
    const num = Number(ufs && ufs[key]);
    console.log(`[GET /api/products/${pid}/servings] Raw value: ${ufs && ufs[key]}, parsed: ${num}`);
    const result = Number.isFinite(num) ? num : null;
    console.log(`[GET /api/products/${pid}/servings] Returning: ${result}`);
    res.json({ servings: result });
  } catch (e) {
    res.status(400).json({ error: String(e && e.message || e) });
  }
});

app.put('/api/products/:productId/servings', async (req, res) => {
  try {
    const pid = Number(req.params.productId);
    if (!Number.isFinite(pid)) return res.status(400).json({ error: 'invalid productId' });
    const key = await getServingsKey();
    if (!key) return res.status(400).json({ error: 'Number of Servings userfield not found' });
    const val = Number(req.body && req.body.servings);
    if (!Number.isFinite(val) || val < 0) return res.status(400).json({ error: 'invalid servings' });
    const payload = {}; payload[key] = val;
    await grocyFetch('PUT', `/userfields/products/${pid}`, payload);
    // Keep product conversion in sync: 1 stock unit = <servings> servings
    try { await ensureProductServingsConversion(pid, val); } catch (_) {}
  // Update built-in energy/calories from userfields (calories_per_serving * num_servings)
  try { await updateProductEnergyFromUserfields(pid); } catch (_) {}
    res.json({ status: 'ok' });
  } catch (e) {
    res.status(400).json({ error: String(e && e.message || e) });
  }
});

// Recent new items
app.get('/api/recent-new-items', async (req, res) => {
  await ensureLocationMap();
  res.json(recentNewItems.map((it) => ({
    product_id: it.product_id,
    name: it.name,
    barcode: it.barcode,
    best_before_date: it.best_before_date,
    location_id: it.location_id,
    location_label: it.location_label || (locationIdToLabel && locationIdToLabel[it.location_id]) || null,
    booking_id: it.booking_id,
  })));
});

// Recent modification logs
app.get('/api/mod-logs', (req, res) => {
  res.json(modificationLogs);
});

// Shopping list: get amount for a specific product
app.get('/api/shopping/amount/:product_id', async (req, res) => {
  try {
    const pid = Number(req.params.product_id);
    const listId = Number.isFinite(Number(req.query.shopping_list_id)) ? Number(req.query.shopping_list_id) : 1;
    if (!Number.isFinite(pid) || pid <= 0) return res.status(400).json({ error: 'invalid product_id' });
    
    // Fetch shopping list items - try multiple endpoints
    let items = null;
    const paths = ['/objects/shopping_list', '/stock/shoppinglist'];
    let lastError = null;
    
    for (const path of paths) {
      try {
        console.log(`[shopping/amount] Trying endpoint: ${path}`);
        items = await grocyFetch('GET', path);
        console.log(`[shopping/amount] Success! Got ${items ? items.length : 0} items`);
        break;
      } catch (e) {
        console.error(`[shopping/amount] Failed ${path}:`, e.message.substring(0, 100));
        lastError = e;
        continue;
      }
    }
    
    if (!items) {
      console.error('[shopping/amount] All endpoints failed. Last error:', lastError?.message);
      return res.status(500).json({ error: 'Could not fetch shopping list: ' + (lastError?.message || 'Unknown error') });
    }
    
    const item = items.find(it => Number(it.product_id) === pid && Number(it.shopping_list_id || 1) === listId);
    const amount = item ? Number(item.amount || 0) : 0;
    
    res.json({ product_id: pid, amount, shopping_list_id: listId });
  } catch (e) {
    res.status(400).json({ error: String(e && e.message || e) });
  }
});

// Shopping list: add product by product_id and amount
app.post('/api/shopping/add', async (req, res) => {
  try {
    const pid = Number(req.body && req.body.product_id);
    const amount = Number(req.body && req.body.amount);
    const listId = Number.isFinite(Number(req.body && req.body.shopping_list_id)) ? Number(req.body.shopping_list_id) : 1;
    if (!Number.isFinite(pid) || pid <= 0) return res.status(400).json({ error: 'invalid product_id' });
    const amt = Number.isFinite(amount) && amount > 0 ? amount : 1;
    const payload = { product_id: pid, amount: amt, shopping_list_id: listId };
    await grocyFetch('POST', '/stock/shoppinglist/add-product', payload);
    res.json({ status: 'ok', message: `Added product ${pid} x ${amt} to shopping list ${listId}` });
  } catch (e) {
    res.status(400).json({ error: String(e && e.message || e) });
  }
});

// Shopping list: remove product by product_id and amount
app.post('/api/shopping/remove', async (req, res) => {
  try {
    const pid = Number(req.body && req.body.product_id);
    const amount = Number(req.body && req.body.amount);
    const listId = Number.isFinite(Number(req.body && req.body.shopping_list_id)) ? Number(req.body.shopping_list_id) : 1;
    if (!Number.isFinite(pid) || pid <= 0) return res.status(400).json({ error: 'invalid product_id' });
    const amt = Number.isFinite(amount) && amount > 0 ? amount : 1;
    const payload = { product_id: pid, amount: amt, shopping_list_id: listId };
    await grocyFetch('POST', '/stock/shoppinglist/remove-product', payload);
    res.json({ status: 'ok', message: `Removed product ${pid} x ${amt} from shopping list ${listId}` });
  } catch (e) {
    res.status(400).json({ error: String(e && e.message || e) });
  }
});

// Consume or purchase product (diff-based for real-time updates)
app.post('/api/consume-or-purchase', async (req, res) => {
  try {
    console.log(`[BACKEND] ========== /api/consume-or-purchase CALLED ==========`);
    const pid = Number(req.body && req.body.product_id);
    const amount = Number(req.body && req.body.amount);
    console.log(`[BACKEND] Received: product_id=${pid}, amount=${amount} servings`);
    
    if (!Number.isFinite(pid) || pid <= 0) return res.status(400).json({ error: 'invalid product_id' });
    if (!Number.isFinite(amount)) return res.status(400).json({ error: 'invalid amount' });
    
    if (amount === 0) {
      console.log(`[BACKEND] Amount is 0, no change needed`);
      return res.json({ status: 'ok', message: 'No change needed' });
    }
    
    // Get product to find num_servings
    const key = await getServingsKey();
    let numServings = 1;
    if (key) {
      const ufs = await grocyFetch('GET', `/userfields/products/${pid}`);
      console.log(`[BACKEND] Product ${pid} userfields:`, ufs);
      console.log(`[BACKEND] Servings key: "${key}"`);
      const num = Number(ufs && ufs[key]);
      console.log(`[BACKEND] Raw servings value: ${ufs && ufs[key]}, parsed: ${num}`);
      if (Number.isFinite(num) && num > 0) numServings = num;
    } else {
      console.log(`[BACKEND] No servings key found!`);
    }
    
    // Convert servings to containers
    // amount is already in servings (frontend converted 0 to actual servings)
    const containers = Math.abs(amount) / numServings;
    console.log(`[BACKEND] Converting ${amount} servings ÷ ${numServings} servings/container = ${containers} containers`);
    
    if (amount > 0) {
      // Consume (positive diff means consume more)
      console.log(`[BACKEND] CONSUMING ${containers} containers from product ${pid}`);
      await grocyFetch('POST', `/stock/products/${pid}/consume`, {
        amount: containers,
        spoiled: false
      });
      console.log(`[BACKEND] Consume successful`);
    } else if (amount < 0) {
      // Purchase back (negative diff means add back to stock)
      console.log(`[BACKEND] ADDING BACK ${containers} containers to product ${pid}`);
      await grocyFetch('POST', `/stock/products/${pid}/add`, {
        amount: containers
      });
      console.log(`[BACKEND] Add back successful`);
    }
    
    console.log(`[BACKEND] Operation complete: ${amount} servings (${containers.toFixed(2)} containers)`);
    res.json({ status: 'ok', message: `Processed ${amount} servings (${containers.toFixed(2)} containers) for product ${pid}` });
  } catch (e) {
    console.error(`[BACKEND] ERROR:`, e);
    res.status(400).json({ error: String(e && e.message || e) });
  }
});

// Update meal plan entry servings
app.put('/api/meal-plan/:entryId/servings', async (req, res) => {
  try {
    const entryId = Number(req.params.entryId);
    if (!Number.isFinite(entryId) || entryId <= 0) return res.status(400).json({ error: 'invalid entryId' });
    const servings = Number(req.body && req.body.servings);
    if (!Number.isFinite(servings) || servings < 0) return res.status(400).json({ error: 'invalid servings' });
    
    // Get the meal plan entry to find product_id
    const entry = await grocyFetch('GET', `/objects/meal_plan/${entryId}`);
    const productId = entry && entry.product_id;
    
    if (!productId) return res.status(400).json({ error: 'meal plan entry has no product_id' });
    
    // If servings is 0, convert to num_servings from userfields
    let actualServings = servings;
    if (servings === 0) {
      const key = await getServingsKey();
      if (key) {
        const ufs = await grocyFetch('GET', `/userfields/products/${productId}`);
        const num = Number(ufs && ufs[key]);
        actualServings = Number.isFinite(num) && num > 0 ? num : 1;
      } else {
        actualServings = 1;
      }
    }
    
    // Update the meal plan entry
    await grocyFetch('PUT', `/objects/meal_plan/${entryId}`, {
      product_amount: actualServings
    });
    
    res.json({ status: 'ok', message: `Updated meal plan entry ${entryId} to ${actualServings} servings` });
  } catch (e) {
    res.status(400).json({ error: String(e && e.message || e) });
  }
});

// Minimal proxy endpoints for test script
// Use regex route to capture everything after /api/proxy/
app.all(/^\/api\/proxy\/(.*)$/i, async (req, res) => {
  try {
    const match = req.url.match(/^\/api\/proxy\/(.*)$/i);
    const sub = (match && match[1]) || '';
    const method = req.method;
    const body = (req.body && Object.keys(req.body).length > 0) ? req.body : undefined;
    const result = await grocyFetch(method, '/' + sub, body);
    res.json(result);
  } catch (e) {
    res.status(400).json({ error: String(e && e.message || e) });
  }
});

// Delete a product by barcode: zero inventory, delete barcode rows, delete product
app.delete('/api/products/by-barcode/:barcode', async (req, res) => {
  try {
    const barcode = String(req.params.barcode || '').trim();
    if (!barcode) return res.status(400).json({ error: 'barcode required' });
    // Find mappings
    const barRes = await grocyFetch('GET', '/objects/product_barcodes');
    const rows = Array.isArray(barRes) ? barRes : (barRes && Array.isArray(barRes.data) ? barRes.data : []);
    const targets = rows.filter((r) => r && String(r.barcode) === barcode);
    let deleted = 0;
    for (const row of targets) {
      const pid = Number(row.product_id);
      try { await grocyFetch('POST', `/stock/products/${pid}/inventory`, { new_amount: 0 }); } catch (_) {}
      try { await grocyFetch('DELETE', `/objects/product_barcodes/${row.id}`); } catch (_) {}
      try { await grocyFetch('DELETE', `/objects/products/${pid}`); deleted++; } catch (_) {}
    }
    res.json({ status: 'ok', deleted });
  } catch (e) {
    res.status(400).json({ error: String(e && e.message || e) });
  }
});

// Inline edit: name, best_before_days (int) or best_before_date, location (via label or id)
app.patch('/api/recent-new-items/:productId', async (req, res) => {
  try {
    await ensureLocationMap();
    const pid = Number(req.params.productId);
    if (!Number.isFinite(pid)) return res.status(400).json({ error: 'invalid productId' });
    const item = recentNewItems.find((x) => x.product_id === pid);
    if (!item) return res.status(404).json({ error: 'not found' });

    const updates = req.body || {};
    const changed = await recreateProductAndInventory(item, updates);
    try {
      modificationLogs.unshift({
        ts: new Date().toISOString(),
        type: 'recreate',
        barcode: item.barcode,
        old_product_id: pid,
        new_product_id: changed && changed.product_id,
        name: changed && changed.name,
        location_label: changed && changed.location_label,
        restocked_amount: changed && changed.restocked_amount,
      });
      while (modificationLogs.length > 50) modificationLogs.pop();
    } catch (_) {}
    res.json({ status: 'ok', changed });
  } catch (e) {
    try {
      const pid = Number(req.params.productId);
      modificationLogs.unshift({
        ts: new Date().toISOString(),
        type: 'error',
        product_id: Number.isFinite(pid) ? pid : null,
        error: String(e && e.message || e),
      });
      while (modificationLogs.length > 50) modificationLogs.pop();
    } catch (_) {}
    res.status(400).json({ error: String(e && e.message || e) });
  }
});

function daysFromNow(targetDateStr) {
  try {
    const now = new Date();
    const t = new Date(targetDateStr);
    const ms = t.getTime() - now.getTime();
    const days = Math.floor(ms / (1000 * 60 * 60 * 24));
    return days > 0 ? days : 0;
  } catch (_) {
    return null;
  }
}

function dateStringFromDays(days) {
  try {
    const d = new Date();
    d.setDate(d.getDate() + Number(days || 0));
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd}`;
  } catch (_) {
    return null;
  }
}

async function recreateProductAndInventory(item, updates) {
  // Preconditions
  const pid = Number(item.product_id);
  const barcode = item.barcode;
  if (!barcode) throw new Error('Recent item missing barcode');

  // Read original product and quantity
  const original = await grocyFetch('GET', `/objects/products/${pid}`);
  if (!original || !Number.isFinite(Number(original.qu_id_purchase)) || !Number.isFinite(Number(original.qu_id_stock))) {
    throw new Error('Original product missing required unit ids');
  }
  const stockInfo = await grocyFetch('GET', `/stock/products/${pid}`);
  const amount = Number(stockInfo && (stockInfo.stock_amount ?? stockInfo.amount ?? 0));
  if (!Number.isFinite(amount)) throw new Error('Failed to read current quantity');

  // Determine desired fields
  const desiredName = (typeof updates.name === 'string' && updates.name.trim()) ? updates.name.trim() : (item.name || original.name);
  let desiredLocationId = Number(original.location_id);
  if (typeof updates.location_label === 'string') {
    const label = updates.location_label.toLowerCase();
    const mapped = locationMap && locationMap[label];
    if (!Number.isFinite(mapped)) throw new Error('Unknown location label: ' + updates.location_label);
    desiredLocationId = Number(mapped);
  }
  let desiredDefaultBbd = Number(original.default_best_before_days || 0);
  if (Number.isFinite(Number(updates.best_before_days))) desiredDefaultBbd = Number(updates.best_before_days);

  // Delete root product
  await grocyFetch('DELETE', `/objects/products/${pid}`);

  // Re-create root product
  const createPayload = {
    name: desiredName,
    location_id: desiredLocationId,
    qu_id_purchase: Number(original.qu_id_purchase),
    qu_id_stock: Number(original.qu_id_stock),
  };
  if (Number.isFinite(desiredDefaultBbd) && desiredDefaultBbd > 0) createPayload.default_best_before_days = desiredDefaultBbd;
  const created = await grocyFetch('POST', '/objects/products', createPayload);
  const newPid = Number((created && (created.created_object_id || created.id)) || 0);
  if (!Number.isFinite(newPid) || newPid <= 0) throw new Error('Failed to create product');

  // Re-link barcode and re-add quantity
  await grocyFetch('POST', '/objects/product_barcodes', { product_id: newPid, barcode });
  if (amount > 0) {
    const addPayload = { amount };
    if (Number.isFinite(desiredDefaultBbd) && desiredDefaultBbd > 0) {
      const dateStr = dateStringFromDays(desiredDefaultBbd);
      if (dateStr) addPayload.best_before_date = dateStr;
    }
    await grocyFetch('POST', `/stock/products/${newPid}/add`, addPayload);
  }

  // Update memory
  item.product_id = newPid;
  item.name = desiredName;
  item.location_id = desiredLocationId;
  item.location_label = (locationIdToLabel && locationIdToLabel[desiredLocationId]) || item.location_label;
  if (Number.isFinite(desiredDefaultBbd) && desiredDefaultBbd > 0) item.best_before_date = dateStringFromDays(desiredDefaultBbd);

  return {
    product_id: item.product_id,
    name: item.name,
    location_id: item.location_id,
    location_label: item.location_label,
    best_before_date: item.best_before_date || null,
    restocked_amount: amount,
  };
}

// =====================
// Macro Tracking Routes
// =====================

// Get day summary (consumed + planned macros)
app.get('/api/macros/day-summary', async (req, res) => {
  try {
    const day = req.query.day || null;
    const result = await spawnPythonTool('get_day_macros_json', [day]);
    res.json(result);
  } catch (err) {
    console.error('[/api/macros/day-summary] Error:', err);
    res.status(500).json({ error: err.message });
  }
});

// Get recent days with macro activity
app.get('/api/macros/recent-days', async (req, res) => {
  try {
    const page = parseInt(req.query.page || '0', 10);
    const limit = parseInt(req.query.limit || '4', 10);
    
    // Call Python tool to get paginated recent days
    const result = await spawnPythonTool('get_recent_days_json', [page, limit]);
    res.json(result);
  } catch (err) {
    console.error('[/api/macros/recent-days] Error:', err);
    res.status(500).json({ error: err.message });
  }
});

// Get status counts (missing links, prices, placeholders, below min stock, shopping cart value)
app.get('/api/status/counts', async (req, res) => {
  try {
    // Get all products
    const products = await grocyFetch('GET', '/objects/products');
    const productsArray = Array.isArray(products) ? products : [];
    
    // Get all barcodes to check for placeholder items
    const barcodesRes = await grocyFetch('GET', '/objects/product_barcodes');
    const barcodes = Array.isArray(barcodesRes) ? barcodesRes : (barcodesRes && barcodesRes.data) || [];
    const productIdsWithBarcodes = new Set(barcodes.map(b => Number(b.product_id)));
    
    let missingLinks = 0;
    let missingPrices = 0;
    let placeholderCount = 0;
    let belowMinCount = 0;
    
    for (const product of productsArray) {
      try {
        const pid = Number(product.id);
        
        // Placeholder items: any item that does not have a barcode
        if (!productIdsWithBarcodes.has(pid)) {
          placeholderCount++;
        }
        
        const userfields = await grocyFetch('GET', `/userfields/products/${pid}`);
        
        // Find walmart_link and not_walmart fields
        let walmartLink = '';
        let notWalmart = false;
        
        if (userfields) {
          for (const key of Object.keys(userfields)) {
            const keyLower = key.toLowerCase();
            
            // Find walmart_link field (but exclude not_walmart)
            if ((keyLower === 'walmart_link' || (keyLower.endsWith('walmart_link') && !keyLower.includes('not')))) {
              walmartLink = userfields[key] ? String(userfields[key]) : '';
            }
            
            // Find not_walmart flag
            if (keyLower === 'not_walmart' || keyLower === 'notwalmartlink') {
              notWalmart = userfields[key] === true || userfields[key] === 1 || userfields[key] === '1';
            }
          }
        }
        
        const hasLink = walmartLink && walmartLink.includes('http');
        
        // Missing links: items that DON'T have the not_walmart flag set to true AND have a missing link
        if (!hasLink && !notWalmart) {
          missingLinks++;
        }
        
        // Check price
        let hasPrice = false;
        try {
          const stockDetails = await grocyFetch('GET', `/stock/products/${pid}`);
          const lastPrice = stockDetails?.last_price || stockDetails?.current_price;
          hasPrice = lastPrice && parseFloat(lastPrice) > 0;
          
          // Check if below minimum stock
          const minStock = Number(product.min_stock_amount || 0);
          const currentStock = Number(stockDetails?.stock_amount || stockDetails?.amount || 0);
          if (minStock > 0 && currentStock < minStock) {
            belowMinCount++;
          }
        } catch (e) {
          hasPrice = false;
        }
        
        // Missing prices: items that have a link but no price OR have no link and no price but not_walmart flag is true
        if ((hasLink && !hasPrice) || (!hasLink && !hasPrice && notWalmart)) {
          missingPrices++;
        }
      } catch (e) {
        // Skip products that error
        continue;
      }
    }
    
    // Get shopping cart value
    let shoppingCartValue = 0;
    try {
      const shoppingListId = 1; // Default shopping list
      const shoppingList = await grocyFetch('GET', `/objects/shopping_list?query[]=shopping_list_id=${shoppingListId}`);
      const shoppingItems = Array.isArray(shoppingList) ? shoppingList : (shoppingList && shoppingList.data) || [];
      
      for (const item of shoppingItems) {
        try {
          const productId = Number(item.product_id);
          const amount = Number(item.amount || 1);
          
          if (!Number.isFinite(productId) || productId <= 0) continue;
          
          // Get product price
          const stockDetails = await grocyFetch('GET', `/stock/products/${productId}`);
          const price = parseFloat(stockDetails?.last_price || stockDetails?.current_price || 0);
          
          if (price > 0) {
            shoppingCartValue += price * amount;
          }
        } catch (e) {
          // Skip items that error
          continue;
        }
      }
    } catch (err) {
      console.error('[shopping_cart_value] Error:', err);
    }
    
    res.json({
      missing_walmart_links: missingLinks,
      missing_prices: missingPrices,
      placeholder_count: placeholderCount,
      below_min_count: belowMinCount,
      shopping_cart_value: shoppingCartValue.toFixed(2)
    });
  } catch (err) {
    console.error('[/api/status/counts] Error:', err);
    res.status(500).json({ error: err.message });
  }
});

// Create temp item
app.post('/api/temp-items', async (req, res) => {
  try {
    const { name, calories, carbs, fats, protein, day } = req.body;
    const result = await spawnPythonTool('create_temp_item_json', [name, calories, carbs, fats, protein, day]);
    res.json(result);
  } catch (err) {
    console.error('[/api/temp-items POST] Error:', err);
    res.status(500).json({ error: err.message });
  }
});

// Delete temp item
app.delete('/api/temp-items/:id', async (req, res) => {
  try {
    const tempItemId = parseInt(req.params.id, 10);
    const result = await spawnPythonTool('delete_temp_item_json', [tempItemId]);
    res.json(result);
  } catch (err) {
    console.error('[/api/temp-items DELETE] Error:', err);
    res.status(500).json({ error: err.message });
  }
});

// Mark meal plan entry as done
app.post('/api/meal-plan/:entryId/mark-done', async (req, res) => {
  try {
    const entryId = parseInt(req.params.entryId, 10);
    const result = await spawnPythonTool('mark_meal_plan_done_json', [entryId]);
    res.json(result);
  } catch (err) {
    console.error('[/api/meal-plan/:entryId/mark-done] Error:', err);
    res.status(500).json({ error: err.message });
  }
});

// Placeholder matching
app.post('/api/placeholder/match', async (req, res) => {
  try {
    const { product_name } = req.body;
    // Call Python placeholder_matcher module
    const result = await spawnPythonScript(
      path.join(__dirname, '..', 'grocy_pig', 'placeholder_matcher.py'),
      ['match', product_name]
    );
    res.json({ product_id: result.matched_product_id || null });
  } catch (err) {
    console.error('[/api/placeholder/match] Error:', err);
    res.status(500).json({ error: err.message });
  }
});

// Override placeholder with real data
app.post('/api/placeholder/override', async (req, res) => {
  try {
    const { product_id, data, barcode } = req.body;
    // Call Python placeholder_matcher module
    await spawnPythonScript(
      path.join(__dirname, '..', 'grocy_pig', 'placeholder_matcher.py'),
      ['override', product_id, JSON.stringify(data)]
    );
    
    // Link barcode to product
    if (barcode) {
      await grocyFetch('POST', '/objects/product_barcodes', { product_id, barcode });
    }
    
    res.json({ status: 'ok' });
  } catch (err) {
    console.error('[/api/placeholder/override] Error:', err);
    res.status(500).json({ error: err.message });
  }
});

// Get shopping list cart links
app.get('/api/shopping/cart-links', async (req, res) => {
  try {
    const shoppingListId = parseInt(req.query.shopping_list_id || '1', 10);
    const result = await spawnPythonTool('get_shopping_list_cart_links_json', [shoppingListId]);
    
    // Result is now plain text format "NAME: LINK\nNAME: LINK"
    // Parse it into an array of {name, link} objects for the client
    if (typeof result === 'string') {
      const lines = result.split('\n').filter(l => l.trim());
      const items = lines.map(line => {
        const colonIndex = line.indexOf(':');
        if (colonIndex === -1) return null;
        const name = line.substring(0, colonIndex).trim();
        const link = line.substring(colonIndex + 1).trim();
        return { name, link };
      }).filter(Boolean);
      
      res.json({ items });
    } else {
      // Handle error format
      res.json({ items: [], error: result.error || 'Unknown error' });
    }
  } catch (err) {
    console.error('[/api/shopping/cart-links] Error:', err);
    res.status(500).json({ error: err.message, items: [] });
  }
});

// Get max protein per 100 cal for slider (4th highest recipe)
app.get('/api/recipes/protein-max', async (req, res) => {
  try {
    const resultStr = await spawnPythonTool('get_recipe_protein_max_json', []);
    const result = typeof resultStr === 'string' ? JSON.parse(resultStr) : resultStr;
    res.json(result);
  } catch (err) {
    console.error('[/api/recipes/protein-max] Error:', err);
    res.status(500).json({ error: err.message, max_protein_per_100cal: 10 });
  }
});

// Get all recipe protein densities for percentile calculation
app.get('/api/recipes/protein-densities', async (req, res) => {
  try {
    const resultStr = await spawnPythonTool('get_recipe_protein_densities_json', []);
    const result = typeof resultStr === 'string' ? JSON.parse(resultStr) : resultStr;
    res.json(result);
  } catch (err) {
    console.error('[/api/recipes/protein-densities] Error:', err);
    res.status(500).json({ error: err.message, recipes: [] });
  }
});

// Get all recipe carbs densities for percentile calculation
app.get('/api/recipes/carbs-densities', async (req, res) => {
  try {
    const resultStr = await spawnPythonTool('get_recipe_carbs_densities_json', []);
    const result = typeof resultStr === 'string' ? JSON.parse(resultStr) : resultStr;
    res.json(result);
  } catch (err) {
    console.error('[/api/recipes/carbs-densities] Error:', err);
    res.status(500).json({ error: err.message, recipes: [] });
  }
});

// Recipe search with filters
app.get('/api/recipes/search', async (req, res) => {
  try {
    const args = [];

    // Parse filters from query params
    if (req.query.can_be_made === 'true') {
      args.push(true);
    } else {
      args.push(null);
    }

    // Macro filters (per 100 cal)
    args.push(req.query.min_carbs_per_100cal ? parseFloat(req.query.min_carbs_per_100cal) : null);
    args.push(req.query.max_carbs_per_100cal ? parseFloat(req.query.max_carbs_per_100cal) : null);
    args.push(req.query.min_fats_per_100cal ? parseFloat(req.query.min_fats_per_100cal) : null);
    args.push(req.query.max_fats_per_100cal ? parseFloat(req.query.max_fats_per_100cal) : null);
    args.push(req.query.min_protein_per_100cal ? parseFloat(req.query.min_protein_per_100cal) : null);
    args.push(req.query.max_protein_per_100cal ? parseFloat(req.query.max_protein_per_100cal) : null);

    // Time filters (minutes)
    args.push(req.query.min_active_time ? parseInt(req.query.min_active_time) : null);
    args.push(req.query.max_active_time ? parseInt(req.query.max_active_time) : null);
    args.push(req.query.min_total_time ? parseInt(req.query.min_total_time) : null);
    args.push(req.query.max_total_time ? parseInt(req.query.max_total_time) : null);

    const resultStr = await spawnPythonTool('get_filtered_recipes_json', args);
    const recipes = typeof resultStr === 'string' ? JSON.parse(resultStr) : resultStr;
    res.json({ recipes });
  } catch (err) {
    console.error('[/api/recipes/search] Error:', err);
    res.status(500).json({ error: err.message, recipes: [] });
  }
});

// Get products missing Walmart links or prices
app.get('/api/missing-walmart', async (req, res) => {
  try {
    const limit = parseInt(req.query.limit || '5', 10);
    const offset = parseInt(req.query.offset || '0', 10);
    
    // Get all products
    const products = await grocyFetch('GET', '/objects/products');
    const productsArray = Array.isArray(products) ? products : (products && products.data) || [];
    
    // Get userfield definitions to find walmart_link and not_walmart keys
    const defs = await grocyFetch('GET', '/objects/userfields');
    const userfields = Array.isArray(defs) ? defs : (defs && defs.data) || [];
    
    // Find the walmart_link and not_walmart userfield keys
    let walmartLinkKey = null;
    let notWalmartKey = null;
    
    for (const def of userfields) {
      const entity = (def.entity || def.object_name || '').toLowerCase();
      if (entity !== 'products') continue;
      
      const name = def.name || def.key || '';
      const caption = def.caption || def.title || '';
      
      // Look for walmart_link (but not "not_walmart")
      if ((name.toLowerCase().includes('walmart') && name.toLowerCase().includes('link')) ||
          (caption.toLowerCase().includes('walmart') && caption.toLowerCase().includes('link'))) {
        if (!name.toLowerCase().includes('not_walmart') && !name.toLowerCase().includes('notwalmartlink')) {
          walmartLinkKey = name;
        }
      }
      
      // Look for not_walmart flag
      if (name.toLowerCase() === 'not_walmart' || name.toLowerCase() === 'notwalmartlink') {
        notWalmartKey = name;
      }
    }
    
    const results = [];
    
    // Process each product
    for (const product of productsArray) {
      try {
        // Skip if not a root product (has parent)
        const parentId = product.parent_product_id;
        if (parentId && (parseInt(parentId) !== 0)) continue;
        
        const pid = parseInt(product.id);
        const name = product.name || 'Unknown';
        
        // Get userfields for this product
        let productUserfields = {};
        try {
          productUserfields = await grocyFetch('GET', `/userfields/products/${pid}`) || {};
        } catch (e) {
          // Skip if can't fetch userfields
          continue;
        }
        
        // Check not_walmart flag
        const notWalmart = notWalmartKey && (productUserfields[notWalmartKey] === true || productUserfields[notWalmartKey] === 1 || productUserfields[notWalmartKey] === '1');
        
        // Check walmart link
        const walmartLink = walmartLinkKey && productUserfields[walmartLinkKey] ? String(productUserfields[walmartLinkKey]) : '';
        const hasMissingLink = !walmartLink || !walmartLink.includes('http');
        
        // Check price
        let hasPrice = false;
        try {
          const stockDetails = await grocyFetch('GET', `/stock/products/${pid}`);
          const lastPrice = stockDetails?.last_price || stockDetails?.current_price;
          hasPrice = lastPrice && parseFloat(lastPrice) > 0;
        } catch (e) {
          // Assume no price if can't check
          hasPrice = false;
        }
        
        // Include if:
        // 1. Missing link AND not_walmart flag is false/missing
        // 2. OR missing price
        const includeDueToLink = hasMissingLink && !notWalmart;
        const includeDueToPrice = !hasPrice;
        
        if (includeDueToLink || includeDueToPrice) {
          results.push({
            id: pid,
            name: name,
            url: `https://www.walmart.com/search?q=${encodeURIComponent(name)}`,
            missing_link: hasMissingLink,
            missing_price: !hasPrice,
            not_walmart: notWalmart
          });
        }
      } catch (e) {
        // Skip products that error
        continue;
      }
    }
    
    // Sort by name for consistency
    results.sort((a, b) => a.name.localeCompare(b.name));
    
    // Apply pagination
    const paginatedResults = results.slice(offset, offset + limit);
    
    res.json({
      items: paginatedResults,
      total: results.length,
      offset: offset,
      limit: limit,
      has_more: (offset + limit) < results.length
    });
  } catch (err) {
    console.error('[/api/missing-walmart] Error:', err);
    res.status(500).json({ error: err.message, items: [] });
  }
});

// Refresh processed values: update recipe macros and add below min stock to shopping list
app.post('/api/refresh-processed-values', async (req, res) => {
  try {
    console.log('[refresh-processed-values] Starting...');
    const results = {
      update_recipe_macros: { status: 'pending', output: '', error: '' },
      add_below_min_to_shopping: { status: 'pending', output: '', error: '' }
    };
    
    // Helper to run Python script and capture text output
    const runPythonTextScript = async (scriptPath) => {
      return new Promise((resolve, reject) => {
        const pythonPath = process.env.PYTHON_PATH || 'python';
        const proc = spawn(pythonPath, [scriptPath]);
        let stdout = '';
        let stderr = '';
        
        proc.stdout.on('data', (data) => { stdout += data.toString(); });
        proc.stderr.on('data', (data) => { stderr += data.toString(); });
        
        proc.on('close', (code) => {
          if (code !== 0) {
            return reject(new Error(`Script failed with code ${code}: ${stderr}`));
          }
          resolve(stdout);
        });
      });
    };
    
    // Run update_recipe_macros.py
    try {
      console.log('[refresh-processed-values] Running update_recipe_macros.py...');
      const updateRecipeResult = await runPythonTextScript(
        path.join(__dirname, '..', 'helpers', 'update_recipe_macros.py')
      );
      results.update_recipe_macros.status = 'success';
      results.update_recipe_macros.output = updateRecipeResult;
      console.log('[refresh-processed-values] update_recipe_macros.py completed');
    } catch (err) {
      console.error('[refresh-processed-values] update_recipe_macros.py failed:', err);
      results.update_recipe_macros.status = 'error';
      results.update_recipe_macros.error = err.message;
    }
    
    // Run add_below_min_to_shopping.py
    try {
      console.log('[refresh-processed-values] Running add_below_min_to_shopping.py...');
      const addBelowMinResult = await runPythonTextScript(
        path.join(__dirname, '..', 'helpers', 'add_below_min_to_shopping.py')
      );
      results.add_below_min_to_shopping.status = 'success';
      results.add_below_min_to_shopping.output = addBelowMinResult;
      console.log('[refresh-processed-values] add_below_min_to_shopping.py completed');
    } catch (err) {
      console.error('[refresh-processed-values] add_below_min_to_shopping.py failed:', err);
      results.add_below_min_to_shopping.status = 'error';
      results.add_below_min_to_shopping.error = err.message;
    }
    
    // Determine overall status
    const overallStatus = (
      results.update_recipe_macros.status === 'success' &&
      results.add_below_min_to_shopping.status === 'success'
    ) ? 'success' : 'partial';
    
    res.json({
      status: overallStatus,
      results: results,
      message: overallStatus === 'success' 
        ? 'All processed values refreshed successfully'
        : 'Some operations failed - check results for details'
    });
  } catch (err) {
    console.error('[/api/refresh-processed-values] Error:', err);
    res.status(500).json({ error: err.message });
  }
});

// Import shopping list (purchase all non-placeholder items from shopping list)
app.post('/api/import-shopping-list', async (req, res) => {
  try {
    console.log('[import-shopping-list] Starting...');
    
    const shoppingListId = req.body && req.body.shopping_list_id ? parseInt(req.body.shopping_list_id) : 1;
    
    const result = await spawnPythonTool('import_shopping_list_json', [shoppingListId]);
    
    // spawnPythonTool already parses the JSON, so result is already an object
    const parsed = typeof result === 'string' ? JSON.parse(result) : result;
    
    if (parsed.status === 'ok') {
      console.log(`[import-shopping-list] Success: ${parsed.message}`);
      res.json(parsed);
    } else {
      console.error(`[import-shopping-list] Error: ${parsed.message}`);
      res.status(400).json(parsed);
    }
  } catch (err) {
    console.error('[/api/import-shopping-list] Error:', err);
    res.status(500).json({ 
      status: 'error',
      message: err.message 
    });
  }
});

// =====================
// Walmart Manager Routes
// =====================

// Get first 5 products with missing walmart links
app.get('/api/walmart/missing-links-batch', async (req, res) => {
  try {
    const limit = parseInt(req.query.limit || '5', 10);
    
    // Get all products
    const products = await grocyFetch('GET', '/objects/products');
    const productsArray = Array.isArray(products) ? products : (products && products.data) || [];
    
    // Get userfield definitions to find walmart_link and not_walmart keys
    const defs = await grocyFetch('GET', '/objects/userfields');
    const userfields = Array.isArray(defs) ? defs : (defs && defs.data) || [];
    
    // Find the walmart_link and not_walmart userfield keys
    let walmartLinkKey = null;
    let notWalmartKey = null;
    
    for (const def of userfields) {
      const entity = (def.entity || def.object_name || '').toLowerCase();
      if (entity !== 'products') continue;
      
      const name = def.name || def.key || '';
      
      // Look for walmart_link (but not "not_walmart")
      if ((name.toLowerCase().includes('walmart') && name.toLowerCase().includes('link'))) {
        if (!name.toLowerCase().includes('not_walmart') && !name.toLowerCase().includes('notwalmartlink')) {
          walmartLinkKey = name;
        }
      }
      
      // Look for not_walmart flag
      if (name.toLowerCase() === 'not_walmart' || name.toLowerCase() === 'notwalmartlink') {
        notWalmartKey = name;
      }
    }
    
    const results = [];
    
    // Process each product
    for (const product of productsArray) {
      if (results.length >= limit) break;
      
      try {
        // Skip if not a root product (has parent)
        const parentId = product.parent_product_id;
        if (parentId && (parseInt(parentId) !== 0)) continue;
        
        const pid = parseInt(product.id);
        const name = product.name || 'Unknown';
        
        // Get userfields for this product
        let productUserfields = {};
        try {
          productUserfields = await grocyFetch('GET', `/userfields/products/${pid}`) || {};
        } catch (e) {
          continue;
        }
        
        // Check not_walmart flag
        const notWalmart = notWalmartKey && (productUserfields[notWalmartKey] === true || productUserfields[notWalmartKey] === 1 || productUserfields[notWalmartKey] === '1');
        
        // Check walmart link
        const walmartLink = walmartLinkKey && productUserfields[walmartLinkKey] ? String(productUserfields[walmartLinkKey]) : '';
        const hasMissingLink = !walmartLink || !walmartLink.includes('http');
        
        // Include only if missing link and not flagged as not_walmart
        if (hasMissingLink && !notWalmart) {
          results.push({
            id: pid,
            name: name
          });
        }
      } catch (e) {
        continue;
      }
    }
    
    res.json({
      products: results,
      total: results.length
    });
  } catch (err) {
    console.error('[/api/walmart/missing-links-batch] Error:', err);
    res.status(500).json({ error: err.message, products: [] });
  }
});

// Scrape a single Walmart product page for price
app.post('/api/walmart/scrape-product', async (req, res) => {
  try {
    let { url } = req.body;
    
    if (!url || typeof url !== 'string') {
      return res.status(400).json({ error: 'url required' });
    }
    
    // Clean the URL
    url = cleanWalmartUrl(url);
    
    console.log(`Scraping product page: ${url}`);
    
    // Call Python scraper script
    const productData = await spawnPythonScraper('scrape_walmart_product.py', [url]);
    
    res.json({
      title: productData.title || null,
      price: productData.price || null,
      price_per_unit: productData.price_per_unit || null,
      image_url: productData.image_url || null
    });
  } catch (err) {
    console.error('[/api/walmart/scrape-product] Error:', err);
    res.status(500).json({ error: err.message });
  }
});

// Scrape Walmart search results for multiple products (with 5 parallel workers)
app.post('/api/walmart/scrape-search', async (req, res) => {
  try {
    const { products } = req.body;
    
    if (!Array.isArray(products) || products.length === 0) {
      return res.status(400).json({ error: 'products array required' });
    }
    
    const metadata = {};
    
    // Process products with 5 parallel workers
    const results = await processWithWorkerPool(products, async (product) => {
      const { id, name } = product;
      
      console.log(`[Worker] Scraping Walmart search for: ${name}`);
      
      // Call Python scraper script
      const searchResults = await spawnPythonScraper('scrape_walmart_search.py', [name]);
      
      // Store metadata for location checking
      if (searchResults.search_information || searchResults.search_metadata || searchResults.search_parameters) {
        metadata[id] = {
          search_information: searchResults.search_information,
          search_metadata: searchResults.search_metadata,
          search_parameters: searchResults.search_parameters
        };
      }
      
      // Extract products from results
      const scrapedProducts = searchResults.products || [];
      
      // Format results (keep only first 4)
      const formatted = scrapedProducts.slice(0, 4).map(p => ({
        name: p.name,
        price: p.price,
        image_url: p.image_url,
        product_url: p.product_url
      }));
      
      console.log(`[Worker] Found ${formatted.length} options for ${name}`);
      
      return formatted;
    }, 5);
    
    res.json({ results, metadata });
  } catch (err) {
    console.error('[/api/walmart/scrape-search] Error:', err);
    res.status(500).json({ error: err.message });
  }
});

// Update selected Walmart links and prices
app.post('/api/walmart/update-selections', async (req, res) => {
  try {
    const { updates } = req.body;
    
    if (!Array.isArray(updates) || updates.length === 0) {
      return res.status(400).json({ error: 'updates array required' });
    }
    
    // Find walmart_link userfield key
    const defs = await grocyFetch('GET', '/objects/userfields');
    const userfields = Array.isArray(defs) ? defs : (defs && defs.data) || [];
    
    let walmartLinkKey = null;
    for (const def of userfields) {
      const entity = (def.entity || def.object_name || '').toLowerCase();
      if (entity !== 'products') continue;
      
      const name = def.name || def.key || '';
      if ((name.toLowerCase().includes('walmart') && name.toLowerCase().includes('link'))) {
        if (!name.toLowerCase().includes('not_walmart') && !name.toLowerCase().includes('notwalmartlink')) {
          walmartLinkKey = name;
          break;
        }
      }
    }
    
    if (!walmartLinkKey) {
      return res.status(400).json({ error: 'walmart_link userfield not found' });
    }
    
    const updateResults = [];
    
    // Process each update
    for (const update of updates) {
      const { product_id, price } = update;
      let { walmart_link } = update;
      
      try {
        // Update walmart_link userfield
        if (walmart_link) {
          // Clean the URL before saving
          walmart_link = cleanWalmartUrl(walmart_link);
          
          const payload = {};
          payload[walmartLinkKey] = walmart_link;
          await grocyFetch('PUT', `/userfields/products/${product_id}`, payload);
        }
        
        // Update price using helpers/tool.py (if price exists)
        if (price && price !== null && price !== 'null') {
          const priceNum = parseFloat(price.toString().replace('$', ''));
          if (priceNum > 0 && !isNaN(priceNum)) {
            await spawnPythonTool('set_product_price_json', [product_id, priceNum]);
          }
        }
        
        updateResults.push({
          product_id,
          status: 'ok',
          updated_link: !!walmart_link,
          updated_price: !!price
        });
        
        console.log(`Updated product ${product_id}: link=${!!walmart_link}, price=${!!price}`);
      } catch (err) {
        console.error(`Error updating product ${product_id}:`, err.message);
        updateResults.push({
          product_id,
          status: 'error',
          error: err.message
        });
      }
    }
    
    res.json({
      status: 'ok',
      results: updateResults
    });
  } catch (err) {
    console.error('[/api/walmart/update-selections] Error:', err);
    res.status(500).json({ error: err.message });
  }
});

// Mark products as not_walmart
app.post('/api/walmart/mark-not-walmart', async (req, res) => {
  try {
    const { product_ids } = req.body;
    
    if (!Array.isArray(product_ids) || product_ids.length === 0) {
      return res.status(400).json({ error: 'product_ids array required' });
    }
    
    // Get userfield definitions to find not_walmart key
    const defs = await grocyFetch('GET', '/objects/userfields');
    const userfields = Array.isArray(defs) ? defs : (defs && defs.data) || [];
    
    let notWalmartKey = null;
    for (const def of userfields) {
      const entity = (def.entity || def.object_name || '').toLowerCase();
      if (entity !== 'products') continue;
      
      const name = def.name || def.key || '';
      if (name.toLowerCase() === 'not_walmart' || name.toLowerCase() === 'notwalmartlink') {
        notWalmartKey = name;
        break;
      }
    }
    
    if (!notWalmartKey) {
      return res.status(400).json({ error: 'not_walmart userfield not found' });
    }
    
    const updateResults = [];
    
    // Update each product
    for (const product_id of product_ids) {
      try {
        const payload = {};
        payload[notWalmartKey] = true;
        await grocyFetch('PUT', `/userfields/products/${product_id}`, payload);
        
        updateResults.push({
          product_id,
          status: 'ok'
        });
        
        console.log(`Marked product ${product_id} as not_walmart`);
      } catch (err) {
        console.error(`Error marking product ${product_id} as not_walmart:`, err.message);
        updateResults.push({
          product_id,
          status: 'error',
          error: err.message
        });
      }
    }
    
    res.json({
      status: 'ok',
      results: updateResults
    });
  } catch (err) {
    console.error('[/api/walmart/mark-not-walmart] Error:', err);
    res.status(500).json({ error: err.message });
  }
});

// Get non-Walmart items that need manual price entry
app.get('/api/walmart/non-walmart-items', async (req, res) => {
  try {
    // Get all products
    const products = await grocyFetch('GET', '/objects/products');
    const productsArray = Array.isArray(products) ? products : (products && products.data) || [];
    
    // Get userfield definitions
    const defs = await grocyFetch('GET', '/objects/userfields');
    const userfields = Array.isArray(defs) ? defs : (defs && defs.data) || [];
    
    let notWalmartKey = null;
    for (const def of userfields) {
      const entity = (def.entity || def.object_name || '').toLowerCase();
      if (entity !== 'products') continue;
      
      const name = def.name || def.key || '';
      if (name.toLowerCase() === 'not_walmart' || name.toLowerCase() === 'notwalmartlink') {
        notWalmartKey = name;
        break;
      }
    }
    
    const nonWalmartItems = [];
    
    // Find products flagged as not_walmart with no price
    for (const product of productsArray) {
      try {
        // Skip if not a root product
        const parentId = product.parent_product_id;
        if (parentId && (parseInt(parentId) !== 0)) continue;
        
        const pid = parseInt(product.id);
        const name = product.name || 'Unknown';
        
        // Get userfields
        let productUserfields = {};
        try {
          productUserfields = await grocyFetch('GET', `/userfields/products/${pid}`) || {};
        } catch (e) {
          continue;
        }
        
        // Check not_walmart flag
        const notWalmart = notWalmartKey && (productUserfields[notWalmartKey] === true || productUserfields[notWalmartKey] === 1 || productUserfields[notWalmartKey] === '1');
        
        if (!notWalmart) continue;
        
        // Check price
        let hasPrice = false;
        try {
          const stockDetails = await grocyFetch('GET', `/stock/products/${pid}`);
          const lastPrice = stockDetails?.last_price || stockDetails?.current_price;
          hasPrice = lastPrice && parseFloat(lastPrice) > 0;
        } catch (e) {
          hasPrice = false;
        }
        
        // Add to list if missing price
        if (!hasPrice) {
          nonWalmartItems.push({
            id: pid,
            name: name
          });
        }
      } catch (e) {
        continue;
      }
    }
    
    res.json({
      items: nonWalmartItems,
      total: nonWalmartItems.length
    });
  } catch (err) {
    console.error('[/api/walmart/non-walmart-items] Error:', err);
    res.status(500).json({ error: err.message, items: [] });
  }
});

// Update manual prices for non-Walmart items
app.post('/api/walmart/update-manual-prices', async (req, res) => {
  try {
    const { updates } = req.body;
    
    if (!Array.isArray(updates) || updates.length === 0) {
      return res.status(400).json({ error: 'updates array required' });
    }
    
    const updateResults = [];
    
    // Process each update
    for (const update of updates) {
      const { product_id, price } = update;
      
      try {
        if (price && price !== null && price !== 'null') {
          const priceNum = parseFloat(price.toString().replace('$', ''));
          if (priceNum > 0 && !isNaN(priceNum)) {
            await spawnPythonTool('set_product_price_json', [product_id, priceNum]);
            updateResults.push({
              product_id,
              status: 'ok'
            });
          } else {
            updateResults.push({
              product_id,
              status: 'error',
              error: 'Invalid price'
            });
          }
        } else {
          updateResults.push({
            product_id,
            status: 'error',
            error: 'No price provided'
          });
        }
      } catch (err) {
        console.error(`Error updating price for product ${product_id}:`, err.message);
        updateResults.push({
          product_id,
          status: 'error',
          error: err.message
        });
      }
    }
    
    res.json({
      status: 'ok',
      results: updateResults
    });
  } catch (err) {
    console.error('[/api/walmart/update-manual-prices] Error:', err);
    res.status(500).json({ error: err.message });
  }
});

// Start background job to update prices for products with Walmart links
app.post('/api/walmart/start-price-update', async (req, res) => {
  try {
    // Get all products
    const products = await grocyFetch('GET', '/objects/products');
    const productsArray = Array.isArray(products) ? products : (products && products.data) || [];
    
    // Get userfield definitions to find walmart_link and not_walmart keys
    const defs = await grocyFetch('GET', '/objects/userfields');
    const userfields = Array.isArray(defs) ? defs : (defs && defs.data) || [];
    
    let walmartLinkKey = null;
    let notWalmartKey = null;
    
    for (const def of userfields) {
      const entity = (def.entity || def.object_name || '').toLowerCase();
      if (entity !== 'products') continue;
      
      const name = def.name || def.key || '';
      
      if ((name.toLowerCase().includes('walmart') && name.toLowerCase().includes('link'))) {
        if (!name.toLowerCase().includes('not_walmart') && !name.toLowerCase().includes('notwalmartlink')) {
          walmartLinkKey = name;
        }
      }
      
      if (name.toLowerCase() === 'not_walmart' || name.toLowerCase() === 'notwalmartlink') {
        notWalmartKey = name;
      }
    }
    
    if (!walmartLinkKey) {
      return res.status(400).json({ error: 'walmart_link userfield not found' });
    }
    
    const productsToUpdate = [];
    
    // Find products with walmart_link but no price (and not flagged as not_walmart)
    for (const product of productsArray) {
      try {
        // Skip if not a root product
        const parentId = product.parent_product_id;
        if (parentId && (parseInt(parentId) !== 0)) continue;
        
        const pid = parseInt(product.id);
        
        // Get userfields
        let productUserfields = {};
        try {
          productUserfields = await grocyFetch('GET', `/userfields/products/${pid}`) || {};
        } catch (e) {
          continue;
        }
        
        // Check not_walmart flag - skip items flagged as not_walmart
        const notWalmart = notWalmartKey && (productUserfields[notWalmartKey] === true || productUserfields[notWalmartKey] === 1 || productUserfields[notWalmartKey] === '1');
        if (notWalmart) continue;
        
        // Check walmart link
        const walmartLink = walmartLinkKey && productUserfields[walmartLinkKey] ? String(productUserfields[walmartLinkKey]) : '';
        const hasLink = walmartLink && walmartLink.includes('http');
        
        if (!hasLink) continue;
        
        // Check price
        let hasPrice = false;
        try {
          const stockDetails = await grocyFetch('GET', `/stock/products/${pid}`);
          const lastPrice = stockDetails?.last_price || stockDetails?.current_price;
          hasPrice = lastPrice && parseFloat(lastPrice) > 0;
        } catch (e) {
          hasPrice = false;
        }
        
        // Add to list if missing price
        if (!hasPrice) {
          productsToUpdate.push({
            id: pid,
            name: product.name,
            walmart_link: walmartLink
          });
        }
      } catch (e) {
        continue;
      }
    }
    
    // Create job
    const jobId = String(nextPriceJobId++);
    const job = {
      id: jobId,
      status: 'running',
      completed: 0,
      total: productsToUpdate.length,
      errors: [],
      products: productsToUpdate
    };
    
    priceUpdateJobs.set(jobId, job);
    
    // Start background processing
    processPriceUpdateJob(job);
    
    res.json({
      job_id: jobId,
      total: productsToUpdate.length
    });
  } catch (err) {
    console.error('[/api/walmart/start-price-update] Error:', err);
    res.status(500).json({ error: err.message });
  }
});

// Get price update job status
app.get('/api/walmart/price-update-status/:jobId', (req, res) => {
  const jobId = req.params.jobId;
  const job = priceUpdateJobs.get(jobId);
  
  if (!job) {
    return res.status(404).json({ error: 'Job not found' });
  }
  
  res.json({
    status: job.status,
    completed: job.completed,
    total: job.total,
    errors: job.errors
  });
});

// Background processor for price update job (with 5 parallel workers)
async function processPriceUpdateJob(job) {
  try {
    // Process products with 5 parallel workers
    await processWithWorkerPool(job.products, async (product) => {
      console.log(`[Worker] Updating price for ${product.name} (${product.id})`);
      
      try {
        // Clean the URL before scraping
        const cleanUrl = cleanWalmartUrl(product.walmart_link);
        
        // Scrape product page for price
        const productData = await spawnPythonScraper('scrape_walmart_product.py', [cleanUrl]);
        
        // Extract price
        const priceStr = productData.price;
        if (priceStr) {
          const priceNum = parseFloat(priceStr.replace('$', ''));
          if (priceNum > 0) {
            // Update price in Grocy
            await spawnPythonTool('set_product_price_json', [product.id, priceNum]);
            console.log(`[Worker] Set price to $${priceNum} for ${product.name}`);
          }
        }
        
        job.completed++;
        return true; // Success
      } catch (err) {
        console.error(`[Worker] Error updating price for ${product.name}:`, err.message);
        job.errors.push({
          product_id: product.id,
          product_name: product.name,
          error: err.message
        });
        job.completed++;
        return false; // Error
      }
    }, 5);
    
    job.status = 'completed';
    console.log(`Price update job ${job.id} completed: ${job.completed}/${job.total}, ${job.errors.length} errors`);
  } catch (err) {
    job.status = 'error';
    job.errors.push({ error: err.message });
    console.error(`Price update job ${job.id} failed:`, err);
  }
}

// Health check endpoint for Luna Hub
app.get('/healthz', (req, res) => {
  res.status(200).json({ status: 'ok' });
});

// Port from command line argument (for Luna) or env variable
const PORT = process.argv[2] || process.env.GROCY_IO_WIZ_PORT || 3100;
app.listen(PORT, '127.0.0.1', () => {
  // eslint-disable-next-line no-console
  const hasBase = !!process.env.GROCY_BASE_URL;
  const hasKey = !!process.env.GROCY_API_KEY;
  console.log(`Server listening on http://127.0.0.1:${PORT}`);
  console.log(`Grocy env detected -> BASE_URL: ${hasBase} API_KEY: ${hasKey}`);
});
