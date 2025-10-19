/**
 * Environment configuration
 */

module.exports = {
  grocy: {
    baseUrl: (process.env.GROCY_BASE_URL || '').replace(/\/$/, ''),
    apiKey: process.env.GROCY_API_KEY,
  },
  openai: {
    apiKey: process.env.OPENAI_API_KEY,
    model: process.env.OPENAI_MODEL || 'gpt-4o-mini',
  },
  nutritionix: {
    appId: process.env.NUTRITIONIX_APP_ID,
    appKey: process.env.NUTRITIONIX_APP_KEY,
  },
  python: {
    path: process.env.PYTHON_PATH || 'python',
  },
  server: {
    port: parseInt(process.env.GROCY_IO_WIZ_PORT || '3100', 10),
  },
};

