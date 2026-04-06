'use strict';

const fs = require('fs');
const path = require('path');
const hookState = require('./hook-state');
const { log } = require('../core/logger');
const { validateSessionId } = require('../state/session-id-validator');
const { atomicWriteSync } = require('../core/atomic-write');
const { resolveSetting } = require('../config/setting-resolver');

/**
 * Session-end hook logic (runtime-agnostic).
 *
 * @param {object} ctx - Internal context contract
 * @param {string} ctx.sessionId
 * @param {string} ctx.cwd
 * @returns {{ action: string, message: null, reason: null }}
 */
function handleSessionEnd(ctx) {
  if (!validateSessionId(ctx.sessionId)) {
    return { action: 'advisory', message: null, reason: null };
  }

  const telemetry = hookState.readAllTelemetry(ctx.sessionId);
  const hasData = Object.keys(telemetry.counters).length > 0
    || Object.keys(telemetry.data).length > 0;

  if (hasData) {
    saveTelemetryToDisk(ctx, telemetry);
    logSessionSummary(ctx.sessionId, telemetry);
  }

  hookState.removeSessionDir(ctx.sessionId);
  return { action: 'advisory', message: null, reason: null };
}

function saveTelemetryToDisk(ctx, telemetry) {
  try {
    const stateDir = resolveSetting('LOOM_STATE_DIR', ctx.cwd) || 'docs/loom';
    const basePath = ctx.cwd || process.cwd();
    const metricsDir = path.isAbsolute(stateDir)
      ? path.join(stateDir, 'metrics')
      : path.join(basePath, stateDir, 'metrics');

    fs.mkdirSync(metricsDir, { recursive: true, mode: 0o700 });

    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    const filename = `session-${ctx.sessionId.slice(0, 12)}-${timestamp}.json`;
    const filePath = path.join(metricsDir, filename);

    const sessionStart = telemetry.timestamps['session-start'] || 0;
    const sessionDurationMs = sessionStart > 0 ? Date.now() - sessionStart : 0;

    const metricsData = {
      sessionId: ctx.sessionId,
      startedAt: sessionStart > 0 ? new Date(sessionStart).toISOString() : null,
      endedAt: new Date().toISOString(),
      durationMs: sessionDurationMs,
      agentDispatches: telemetry.counters['agent-dispatches'] || 0,
      agentCompletions: telemetry.counters['agent-completions'] || 0,
      agentStats: telemetry.data['agent-stats'] || [],
    };

    const manifests = {};
    for (const [key, value] of Object.entries(telemetry.data)) {
      if (key.startsWith('manifest-')) {
        manifests[key.slice('manifest-'.length)] = value;
      }
    }
    if (Object.keys(manifests).length > 0) {
      metricsData.fileManifests = manifests;
    }

    atomicWriteSync(filePath, JSON.stringify(metricsData, null, 2));
    log('INFO', `SessionEnd: Telemetry saved to ${filePath}`);
  } catch (err) {
    log('WARN', `SessionEnd: Failed to save telemetry: ${err.message}`);
  }
}

function logSessionSummary(sessionId, telemetry) {
  const dispatches = telemetry.counters['agent-dispatches'] || 0;
  const completions = telemetry.counters['agent-completions'] || 0;
  const stats = telemetry.data['agent-stats'] || [];

  const totalFilesChanged = stats.reduce((sum, s) => sum + (s.filesChanged || 0), 0);
  const agentNames = [...new Set(stats.map((s) => s.agent).filter(Boolean))];

  const parts = [`Session ${sessionId.slice(0, 8)} summary:`];
  parts.push(`  Agents dispatched: ${dispatches}`);
  parts.push(`  Agents completed: ${completions}`);
  if (agentNames.length > 0) {
    parts.push(`  Agents used: ${agentNames.join(', ')}`);
  }
  if (totalFilesChanged > 0) {
    parts.push(`  Total files changed: ${totalFilesChanged}`);
  }

  const sessionStart = telemetry.timestamps['session-start'] || 0;
  if (sessionStart > 0) {
    const durationSec = Math.round((Date.now() - sessionStart) / 1000);
    const minutes = Math.floor(durationSec / 60);
    const seconds = durationSec % 60;
    parts.push(`  Session duration: ${minutes}m ${seconds}s`);
  }

  log('INFO', `SessionEnd: ${parts.join('\n')}`);
}

module.exports = { handleSessionEnd };
