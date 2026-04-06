'use strict';

const fs = require('fs');
const hookState = require('./hook-state');
const state = require('../state/session-state');
const { log } = require('../core/logger');
const { validateSessionId } = require('../state/session-id-validator');

const SERVICE_ENV_VARS = [
  { name: 'OLLAMA_BASE_URL', label: 'Ollama (local inference)' },
  { name: 'LITELLM_MASTER_KEY', label: 'LiteLLM (model proxy)' },
  { name: 'NEO4J_URI', label: 'Neo4j (knowledge graph)' },
];

/**
 * Session-start hook logic (runtime-agnostic).
 *
 * @param {object} ctx - Internal context contract
 * @param {string} ctx.sessionId
 * @param {string} ctx.cwd
 * @returns {{ action: string, message: string|null, reason: null }}
 */
function handleSessionStart(ctx) {
  hookState.pruneStale();

  const messageParts = [];

  if (validateSessionId(ctx.sessionId)) {
    hookState.ensureSessionDir(ctx.sessionId);
    hookState.setTimestamp(ctx.sessionId, 'session-start');
  }

  try {
    const baseDir = hookState.getBaseDir();
    fs.accessSync(baseDir, fs.constants.W_OK);
  } catch {
    log('WARN', 'SessionStart: Hook state directory is not writable');
    messageParts.push('[WARN] Hook state directory is not writable -- telemetry will be unavailable');
  }

  if (state.hasActiveSession(ctx.cwd)) {
    try {
      const sessionPath = state.resolveActiveSessionPath(ctx.cwd);
      const content = fs.readFileSync(sessionPath, 'utf8');
      const parts = [];

      const phaseMatch = content.match(/current_phase:\s*(\S+)/);
      if (phaseMatch) parts.push(`phase=${phaseMatch[1]}`);
      const statusMatch = content.match(/status:\s*(\S+)/);
      if (statusMatch) parts.push(`status=${statusMatch[1]}`);
      const taskMatch = content.match(/task_summary:\s*(.+)/);
      if (taskMatch) parts.push(`task="${taskMatch[1].trim()}"`);

      if (parts.length > 0) {
        messageParts.push(`Active Loom session: ${parts.join(', ')}`);
        if (validateSessionId(ctx.sessionId)) {
          hookState.storeJson(ctx.sessionId, 'session-context', {
            hasActiveSession: true,
            phase: phaseMatch ? phaseMatch[1] : null,
            status: statusMatch ? statusMatch[1] : null,
          });
        }
      }
    } catch (err) {
      log('DEBUG', `SessionStart: Could not read active session: ${err.message}`);
    }
  }

  const availableServices = [];
  const unavailableServices = [];
  for (const svc of SERVICE_ENV_VARS) {
    if (process.env[svc.name]) {
      availableServices.push(svc.label);
    } else {
      unavailableServices.push(svc.label);
    }
  }

  if (availableServices.length > 0) {
    log('INFO', `SessionStart: Available services: ${availableServices.join(', ')}`);
  }
  if (unavailableServices.length > 0) {
    log('DEBUG', `SessionStart: Unavailable services: ${unavailableServices.join(', ')}`);
  }

  messageParts.push('Loom orchestration hooks active.');
  if (availableServices.length > 0) {
    messageParts.push(`Services: ${availableServices.join(', ')}`);
  }
  messageParts.push('Commands: /loom:craft, /loom:agent, /loom:review, /loom:debug, /loom:status');

  const message = messageParts.join('\n');
  return { action: 'advisory', message, reason: null };
}

module.exports = { handleSessionStart };
