/**
 * Job queue system for background processing
 */

// In-memory job store (MVP)
const jobStore = new Map(); // jobId -> { id, status, op, barcode, logs: [], result }
let nextJobId = 1;

// Simple FIFO queue; one worker at a time
const queue = [];
let isWorking = false;

// Recent newly created items (max 3)
const recentNewItems = []; // [{ product_id, name, barcode, best_before_date, location_id, location_label, booking_id }]

// Modification logs (last 50)
const modificationLogs = [];

/**
 * Enqueue a job
 * @param {object} job - Job to enqueue
 * @returns {number} Job ID
 */
function enqueueJob(job) {
  const id = nextJobId++;
  const record = { id, status: 'pending', ...job, logs: [], result: null };
  jobStore.set(id, record);
  queue.push(id);
  return id;
}

/**
 * Get job by ID
 * @param {number} id - Job ID
 * @returns {object|null} Job record or null
 */
function getJob(id) {
  return jobStore.get(id) || null;
}

/**
 * Update job status
 * @param {number} id - Job ID
 * @param {string} status - New status
 * @param {object} updates - Additional updates
 */
function updateJob(id, status, updates = {}) {
  const job = jobStore.get(id);
  if (job) {
    job.status = status;
    Object.assign(job, updates);
  }
}

/**
 * Add log to job
 * @param {number} id - Job ID
 * @param {string} message - Log message
 */
function addJobLog(id, message) {
  const job = jobStore.get(id);
  if (job) {
    job.logs.push(message);
  }
}

/**
 * Get recent new items
 * @returns {array} Recent items
 */
function getRecentNewItems() {
  return recentNewItems;
}

/**
 * Add recent new item
 * @param {object} item - Item to add
 */
function addRecentNewItem(item) {
  recentNewItems.unshift(item);
  if (recentNewItems.length > 3) recentNewItems.pop();
}

/**
 * Update recent new item
 * @param {number} productId - Product ID
 * @param {object} updates - Updates to apply
 * @returns {boolean} True if updated
 */
function updateRecentNewItem(productId, updates) {
  const item = recentNewItems.find((i) => i.product_id === productId);
  if (item) {
    Object.assign(item, updates);
    return true;
  }
  return false;
}

/**
 * Get modification logs
 * @returns {array} Modification logs
 */
function getModificationLogs() {
  return modificationLogs;
}

/**
 * Add modification log
 * @param {string} message - Log message
 */
function addModificationLog(message) {
  modificationLogs.unshift(message);
  if (modificationLogs.length > 50) modificationLogs.pop();
}

/**
 * Check if worker is active
 * @returns {boolean} True if working
 */
function isWorkerActive() {
  return isWorking;
}

/**
 * Set worker active state
 * @param {boolean} active - Active state
 */
function setWorkerActive(active) {
  isWorking = active;
}

/**
 * Get next job from queue
 * @returns {number|null} Job ID or null
 */
function getNextJob() {
  return queue.shift() || null;
}

module.exports = {
  enqueueJob,
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
};

