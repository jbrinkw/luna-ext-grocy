/**
 * Python bridge for spawning Python scripts and tools
 */

const { spawn } = require('child_process');
const path = require('path');
const config = require('../config/environment');

/**
 * Spawn a Python tool function
 * @param {string} functionName - Name of the function in lib.api
 * @param {array} args - Function arguments
 * @returns {Promise<any>} Function result
 */
function spawnPythonTool(functionName, ...args) {
  return new Promise((resolve, reject) => {
    const pythonPath = config.python.path;
    const projectRoot = path.join(__dirname, '..', '..');
    const libPath = path.join(projectRoot, 'lib');
    const argsJson = JSON.stringify(args);
    const code = `
import sys
import json
sys.path.insert(0, ${JSON.stringify(libPath)})
from api import ${functionName}
args = json.loads(${JSON.stringify(argsJson)})
result = ${functionName}(*args)
print(json.dumps(result))
`;
    const proc = spawn(pythonPath, ['-c', code], { cwd: projectRoot });
    let stdout = '';
    let stderr = '';
    proc.stdout.on('data', (data) => { stdout += data; });
    proc.stderr.on('data', (data) => { stderr += data; });
    proc.on('close', (code) => {
      if (code !== 0) {
        reject(new Error(`Python exited with code ${code}: ${stderr}`));
      } else {
        try {
          resolve(JSON.parse(stdout));
        } catch (e) {
          resolve(stdout);
        }
      }
    });
    proc.on('error', reject);
  });
}

/**
 * Spawn a Python script
 * @param {string} scriptName - Name of script (relative to project root or scripts/)
 * @param {array} args - Script arguments
 * @returns {Promise<string>} Script output
 */
function spawnPythonScript(scriptName, ...args) {
  return new Promise((resolve, reject) => {
    const pythonPath = config.python.path;
    const projectRoot = path.join(__dirname, '..', '..');
    const libPath = path.join(projectRoot, 'lib');
    // Try both project root and scripts/ directory
    const scriptPaths = [
      path.join(projectRoot, scriptName),
      path.join(projectRoot, 'scripts', scriptName),
    ];
    // Add lib to Python path for imports
    const env = { ...process.env, PYTHONPATH: libPath };
    const proc = spawn(pythonPath, [scriptPaths[0], ...args], { cwd: projectRoot, env });
    let stdout = '';
    let stderr = '';
    proc.stdout.on('data', (data) => { stdout += data; });
    proc.stderr.on('data', (data) => { stderr += data; });
    proc.on('close', (code) => {
      if (code !== 0) {
        // Try second path if first failed
        if (stderr.includes('No such file')) {
          const proc2 = spawn(pythonPath, [scriptPaths[1], ...args], { cwd: projectRoot, env });
          let stdout2 = '';
          let stderr2 = '';
          proc2.stdout.on('data', (data) => { stdout2 += data; });
          proc2.stderr.on('data', (data) => { stderr2 += data; });
          proc2.on('close', (code2) => {
            if (code2 !== 0) {
              reject(new Error(`Python script failed: ${stderr2}`));
            } else {
              resolve(stdout2);
            }
          });
          proc2.on('error', reject);
        } else {
          reject(new Error(`Python script failed: ${stderr}`));
        }
      } else {
        resolve(stdout);
      }
    });
    proc.on('error', reject);
  });
}

/**
 * Spawn a Python scraper script
 * @param {string} scriptName - Name of scraper script in helpers/
 * @param {array} args - Script arguments
 * @returns {Promise<string>} Script output
 */
function spawnPythonScraper(scriptName, ...args) {
  return spawnPythonScript(scriptName, ...args);
}

module.exports = {
  spawnPythonTool,
  spawnPythonScript,
  spawnPythonScraper,
};

