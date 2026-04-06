'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');
const { log } = require('../core/logger');
const { validateSessionId } = require('../state/session-id-validator');
const { atomicWriteSync } = require('../core/atomic-write');
const { resolveSetting } = require('../config/setting-resolver');

const HOOK_STATE_TTL_MS = 2 * 60 * 60 * 1000;

const uid = process.getuid ? process.getuid() : 'default';

function _resolveBaseDir() {
  if (process.env.LOOM_HOOKS_DIR) {
    return process.env.LOOM_HOOKS_DIR;
  }

  const stateDir = resolveSetting('LOOM_STATE_DIR');
  if (stateDir) {
    return path.join(stateDir, 'hooks');
  }

  return path.join(os.tmpdir(), `loom-hooks-${uid}`);
}

const DEFAULT_BASE_DIR = _resolveBaseDir();

function ensureBaseDir(dir) {
  // Check for symlinks BEFORE creating anything
  if (fs.existsSync(dir)) {
    const stats = fs.lstatSync(dir);
    if (stats.isSymbolicLink()) {
      throw new Error('Hook state directory must not be a symlink');
    }
  }
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
}

function createHookState(baseDir = DEFAULT_BASE_DIR) {
  function getBaseDir() {
    return baseDir;
  }

  function pruneStale() {
    ensureBaseDir(baseDir);
    if (!fs.existsSync(baseDir)) return;

    const now = Date.now();
    let entries;
    try {
      entries = fs.readdirSync(baseDir, { withFileTypes: true });
    } catch {
      return;
    }

    for (const entry of entries) {
      if (!entry.isDirectory()) continue;
      const dirPath = path.join(baseDir, entry.name);
      try {
        const stat = fs.lstatSync(dirPath);
        if (now - stat.mtimeMs > HOOK_STATE_TTL_MS) {
          fs.rmSync(dirPath, { recursive: true, force: true });
        }
      } catch {}
    }
  }

  function setActiveAgent(sessionId, agentName) {
    if (!validateSessionId(sessionId)) {
      log('ERROR', 'Invalid session_id: contains unsafe characters');
      return false;
    }
    const agentFile = path.join(baseDir, sessionId, 'active-agent');
    atomicWriteSync(agentFile, agentName);
    return true;
  }

  function getActiveAgent(sessionId) {
    if (!validateSessionId(sessionId)) return '';
    const agentFile = path.join(baseDir, sessionId, 'active-agent');
    try {
      return fs.readFileSync(agentFile, 'utf8').trim();
    } catch {
      return '';
    }
  }

  function clearActiveAgent(sessionId) {
    if (!validateSessionId(sessionId)) return;
    const agentFile = path.join(baseDir, sessionId, 'active-agent');
    try {
      fs.unlinkSync(agentFile);
    } catch {}
  }

  function ensureSessionDir(sessionId) {
    if (!validateSessionId(sessionId)) return false;
    ensureBaseDir(baseDir);
    fs.mkdirSync(path.join(baseDir, sessionId), { recursive: true, mode: 0o700 });
    return true;
  }

  function removeSessionDir(sessionId) {
    if (!validateSessionId(sessionId)) return false;
    try {
      fs.rmSync(path.join(baseDir, sessionId), { recursive: true, force: true });
    } catch {}
    return true;
  }

  function incrementCounter(sessionId, counterName) {
    if (!validateSessionId(sessionId)) return 0;
    const counterFile = path.join(baseDir, sessionId, `counter-${counterName}.json`);
    let current = 0;
    try {
      const raw = fs.readFileSync(counterFile, 'utf8');
      current = JSON.parse(raw).value || 0;
    } catch {}
    const next = current + 1;
    atomicWriteSync(counterFile, JSON.stringify({ value: next, updated: Date.now() }));
    return next;
  }

  function getCounter(sessionId, counterName) {
    if (!validateSessionId(sessionId)) return 0;
    const counterFile = path.join(baseDir, sessionId, `counter-${counterName}.json`);
    try {
      const raw = fs.readFileSync(counterFile, 'utf8');
      return JSON.parse(raw).value || 0;
    } catch {
      return 0;
    }
  }

  function setTimestamp(sessionId, key) {
    if (!validateSessionId(sessionId)) return;
    const tsFile = path.join(baseDir, sessionId, `ts-${key}`);
    atomicWriteSync(tsFile, String(Date.now()));
  }

  function getTimestamp(sessionId, key) {
    if (!validateSessionId(sessionId)) return 0;
    const tsFile = path.join(baseDir, sessionId, `ts-${key}`);
    try {
      return parseInt(fs.readFileSync(tsFile, 'utf8').trim(), 10) || 0;
    } catch {
      return 0;
    }
  }

  function storeJson(sessionId, key, data) {
    if (!validateSessionId(sessionId)) return false;
    const jsonFile = path.join(baseDir, sessionId, `data-${key}.json`);
    atomicWriteSync(jsonFile, JSON.stringify(data));
    return true;
  }

  function loadJson(sessionId, key) {
    if (!validateSessionId(sessionId)) return null;
    const jsonFile = path.join(baseDir, sessionId, `data-${key}.json`);
    try {
      return JSON.parse(fs.readFileSync(jsonFile, 'utf8'));
    } catch {
      return null;
    }
  }

  function appendToList(sessionId, key, item) {
    if (!validateSessionId(sessionId)) return false;
    const existing = loadJson(sessionId, key) || [];
    if (!Array.isArray(existing)) return false;
    existing.push(item);
    return storeJson(sessionId, key, existing);
  }

  function readAllTelemetry(sessionId) {
    if (!validateSessionId(sessionId)) return {};
    const sessionDir = path.join(baseDir, sessionId);
    const telemetry = { counters: {}, timestamps: {}, data: {} };
    try {
      const entries = fs.readdirSync(sessionDir);
      for (const entry of entries) {
        if (entry.startsWith('counter-') && entry.endsWith('.json')) {
          const name = entry.slice('counter-'.length, -'.json'.length);
          try {
            telemetry.counters[name] = JSON.parse(
              fs.readFileSync(path.join(sessionDir, entry), 'utf8')
            ).value || 0;
          } catch {}
        } else if (entry.startsWith('ts-')) {
          const name = entry.slice('ts-'.length);
          try {
            telemetry.timestamps[name] = parseInt(
              fs.readFileSync(path.join(sessionDir, entry), 'utf8').trim(), 10
            ) || 0;
          } catch {}
        } else if (entry.startsWith('data-') && entry.endsWith('.json')) {
          const name = entry.slice('data-'.length, -'.json'.length);
          try {
            telemetry.data[name] = JSON.parse(
              fs.readFileSync(path.join(sessionDir, entry), 'utf8')
            );
          } catch {}
        }
      }
    } catch {}
    return telemetry;
  }

  return {
    getBaseDir,
    pruneStale,
    setActiveAgent,
    getActiveAgent,
    clearActiveAgent,
    ensureSessionDir,
    removeSessionDir,
    incrementCounter,
    getCounter,
    setTimestamp,
    getTimestamp,
    storeJson,
    loadJson,
    appendToList,
    readAllTelemetry,
  };
}

const defaultInstance = createHookState();

module.exports = {
  createHookState,
  DEFAULT_BASE_DIR,
  ...defaultInstance,
};
