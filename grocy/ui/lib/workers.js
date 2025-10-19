/**
 * Worker pool for parallel processing
 */

/**
 * Process items with a worker pool
 * @param {array} items - Items to process
 * @param {function} processFn - Function to process each item (returns Promise)
 * @param {number} maxWorkers - Maximum parallel workers
 * @returns {Promise<array>} Array of results
 */
async function processWithWorkerPool(items, processFn, maxWorkers = 5) {
  const results = [];
  const workers = [];
  let index = 0;

  async function worker() {
    while (index < items.length) {
      const currentIndex = index++;
      const item = items[currentIndex];
      try {
        const result = await processFn(item, currentIndex);
        results[currentIndex] = { success: true, result };
      } catch (error) {
        results[currentIndex] = { success: false, error: error.message };
      }
    }
  }

  // Start workers
  for (let i = 0; i < Math.min(maxWorkers, items.length); i++) {
    workers.push(worker());
  }

  // Wait for all workers to complete
  await Promise.all(workers);

  return results;
}

module.exports = {
  processWithWorkerPool,
};

