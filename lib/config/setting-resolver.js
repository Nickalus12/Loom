'use strict';

const path = require('path');
const { parseEnvFile } = require('../core/env-file-parser');

const DEFAULTS = {
  LOOM_STATE_DIR: 'docs/loom',
  LOOM_DISABLED_AGENTS: '',
  LOOM_MAX_RETRIES: '2',
  LOOM_AUTO_ARCHIVE: 'true',
  LOOM_VALIDATION_STRICTNESS: 'normal',
  LOOM_MAX_CONCURRENT: '0',
  LOOM_EXECUTION_MODE: 'ask',
  LOOM_CRAFT_MODE: 'cloud',
  LOOM_AGENT_TOOL_MODEL: 'qwen3:4b',
  LOOM_AGENT_ANALYSIS_MODEL: 'deepseek-coder-v2:16b',
  NIA_API_KEY: '',
  NIA_ENABLED: 'true',
};

const VALIDATORS = {
  LOOM_EXECUTION_MODE: (v) => ['ask', 'parallel', 'sequential'].includes(v),
  LOOM_CRAFT_MODE: (v) => ['cloud', 'local'].includes(v),
  LOOM_AUTO_ARCHIVE: (v) => ['true', 'false'].includes(v),
  LOOM_VALIDATION_STRICTNESS: (v) => ['strict', 'normal', 'lenient'].includes(v),
  LOOM_MAX_RETRIES: (v) => /^\d+$/.test(v) && parseInt(v, 10) <= 10,
  LOOM_MAX_CONCURRENT: (v) => /^\d+$/.test(v),
  NIA_ENABLED: (v) => ['true', 'false'].includes(v),
};

function resolveSetting(varName, projectRoot) {
  // Precedence: env var > workspace .env > extension .env > default
  const envValue = process.env[varName];
  if (envValue !== undefined && envValue !== '') {
    if (!_validate(varName, envValue)) {
      process.stderr.write(`[loom] Invalid value for ${varName}: "${envValue}", using default\n`);
      return DEFAULTS[varName] || null;
    }
    return envValue;
  }

  if (projectRoot) {
    const projectEnv = parseEnvFile(path.join(projectRoot, '.env'));
    if (projectEnv[varName] !== undefined && projectEnv[varName] !== '') {
      if (!_validate(varName, projectEnv[varName])) {
        process.stderr.write(`[loom] Invalid value for ${varName} in .env: "${projectEnv[varName]}", using default\n`);
        return DEFAULTS[varName] || null;
      }
      return projectEnv[varName];
    }
  }

  const extensionRoot = process.env.LOOM_EXTENSION_PATH || process.env.CLAUDE_PLUGIN_ROOT;
  if (extensionRoot) {
    const extEnv = parseEnvFile(path.join(extensionRoot, '.env'));
    if (extEnv[varName] !== undefined && extEnv[varName] !== '') {
      if (!_validate(varName, extEnv[varName])) {
        process.stderr.write(`[loom] Invalid value for ${varName} in extension .env: "${extEnv[varName]}", using default\n`);
        return DEFAULTS[varName] || null;
      }
      return extEnv[varName];
    }
  }

  return DEFAULTS[varName] || null;
}

function _validate(varName, value) {
  const validator = VALIDATORS[varName];
  if (!validator) return true;
  return validator(value);
}

module.exports = { resolveSetting, DEFAULTS, VALIDATORS };
