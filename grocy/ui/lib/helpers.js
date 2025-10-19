/**
 * Shared helper utilities
 */

/**
 * Clean Walmart URL (remove query params)
 * @param {string} url - Walmart URL
 * @returns {string} Cleaned URL
 */
function cleanWalmartUrl(url) {
  if (!url || typeof url !== 'string') return url;
  try {
    const parsed = new URL(url);
    return parsed.origin + parsed.pathname;
  } catch {
    return url;
  }
}

/**
 * Find last JSON object in text
 * @param {string} text - Text to search
 * @returns {object|null} Parsed JSON or null
 */
function findLastJson(text) {
  if (!text || typeof text !== 'string') return null;
  const lines = text.split('\n').reverse();
  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
      try {
        return JSON.parse(trimmed);
      } catch {
        continue;
      }
    }
  }
  return null;
}

/**
 * Find last data object in text
 * @param {string} text - Text to search
 * @returns {object|null} Parsed JSON or null
 */
function findLastData(text) {
  const json = findLastJson(text);
  return json && json.data ? json.data : json;
}

module.exports = {
  cleanWalmartUrl,
  findLastJson,
  findLastData,
};

