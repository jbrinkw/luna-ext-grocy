/**
 * Caching utilities for locations and userfields
 */

const { grocyFetch } = require('./grocy-api');

// Location discovery/cache
let locationMap = null; // { label->id }
let locationIdToLabel = null; // { id->label }

// Userfield key cache
let userfieldKeyCache = null; // { label -> key }

/**
 * Ensure location map is loaded
 */
async function ensureLocationMap() {
  if (locationMap && locationIdToLabel) return;
  try {
    const res = await grocyFetch('GET', '/objects/locations');
    const rows = Array.isArray(res) ? res : (res && Array.isArray(res.data) ? res.data : []);
    const labelToId = {};
    const idToLabel = {};
    const synonyms = {
      fridge: ['fridge', 'refrigerator', 'refrig'],
      freezer: ['freezer'],
      pantry: ['pantry', 'cupboard', 'larder'],
    };
    rows.forEach((row) => {
      const id = Number(row && row.id);
      const name = (row && row.name || '').toString().toLowerCase();
      if (!Number.isFinite(id) || !name) return;
      Object.keys(synonyms).forEach((label) => {
        const words = synonyms[label];
        if (words.some((w) => name === w || name.includes(w))) {
          if (labelToId[label] == null) labelToId[label] = id;
          idToLabel[id] = label;
        }
      });
    });
    locationMap = labelToId;
    locationIdToLabel = idToLabel;
  } catch (e) {
    // ignore
  }
}

/**
 * Get location map
 * @returns {object} Location map { label -> id }
 */
function getLocationMap() {
  return locationMap;
}

/**
 * Get location ID to label map
 * @returns {object} Location ID to label map { id -> label }
 */
function getLocationIdToLabel() {
  return locationIdToLabel;
}

/**
 * Get or load userfield key cache
 * @returns {Promise<object>} Userfield key cache
 */
async function getUserfieldKeys() {
  if (userfieldKeyCache) return userfieldKeyCache;
  try {
    const res = await grocyFetch('GET', '/objects/userfields');
    const rows = Array.isArray(res) ? res : (res && Array.isArray(res.data) ? res.data : []);
    const cache = {};
    rows.forEach((row) => {
      const entity = (row.entity || '').toLowerCase();
      if (entity === 'products') {
        const name = row.name;
        const caption = (row.caption || row.title || '').toLowerCase();
        if (caption.includes('servings') && !cache.servings) cache.servings = name;
        if (caption.includes('ready') && caption.includes('eat') && !cache.ready_to_eat) cache.ready_to_eat = name;
      }
    });
    userfieldKeyCache = cache;
    return cache;
  } catch (e) {
    return {};
  }
}

module.exports = {
  ensureLocationMap,
  getLocationMap,
  getLocationIdToLabel,
  getUserfieldKeys,
};

