'use strict';

const fs = require('fs');
const hookState = require('./hook-state');
const state = require('../state/session-state');
const { log } = require('../core/logger');
const { validateSessionId } = require('../state/session-id-validator');

const VERSION = 'Silk.1.0';

const SERVICE_ENV_VARS = [
  { name: 'OLLAMA_BASE_URL', label: 'Ollama', icon: 'ON' },
  { name: 'LITELLM_MASTER_KEY', label: 'LiteLLM', icon: 'ON' },
  { name: 'NEO4J_URI', label: 'Neo4j', icon: 'ON' },
  { name: 'NIA_API_KEY', label: 'Nia AI', icon: 'ON' },
  { name: 'GEMINI_API_KEY', label: 'Gemini', icon: 'ON' },
];

/**
 * Session-start hook logic (runtime-agnostic).
 */
function handleSessionStart(ctx) {
  hookState.pruneStale();

  if (validateSessionId(ctx.sessionId)) {
    hookState.ensureSessionDir(ctx.sessionId);
    hookState.setTimestamp(ctx.sessionId, 'session-start');
  }

  // Check workspace writability
  let workspaceOk = true;
  try {
    const baseDir = hookState.getBaseDir();
    fs.accessSync(baseDir, fs.constants.W_OK);
  } catch {
    workspaceOk = false;
    log('WARN', 'SessionStart: Hook state directory is not writable');
  }

  // Check for active session
  let activeSession = null;
  if (state.hasActiveSession(ctx.cwd)) {
    try {
      const sessionPath = state.resolveActiveSessionPath(ctx.cwd);
      const content = fs.readFileSync(sessionPath, 'utf8');
      const phaseMatch = content.match(/current_phase:\s*(\S+)/);
      const statusMatch = content.match(/status:\s*(\S+)/);
      const taskMatch = content.match(/task:\s*["']?(.+?)["']?\s*$/m);
      activeSession = {
        phase: phaseMatch ? phaseMatch[1] : '?',
        status: statusMatch ? statusMatch[1] : '?',
        task: taskMatch ? taskMatch[1].substring(0, 50) : '',
      };
      if (validateSessionId(ctx.sessionId)) {
        hookState.storeJson(ctx.sessionId, 'session-context', {
          hasActiveSession: true,
          phase: activeSession.phase,
          status: activeSession.status,
        });
      }
    } catch (err) {
      log('DEBUG', 'SessionStart: Could not read active session: ' + err.message);
    }
  }

  // Check services
  const services = SERVICE_ENV_VARS.map(function(svc) {
    var active = !!process.env[svc.name];
    return { label: svc.label, active: active };
  });
  var activeCount = services.filter(function(s) { return s.active; }).length;

  if (activeCount > 0) {
    log('INFO', 'SessionStart: ' + activeCount + '/' + services.length + ' services available');
  }

  // Build the welcome message
  var lines = [];

  lines.push('');
  lines.push('  _                          ');
  lines.push(' | |    ___   ___  _ __ ___  ');
  lines.push(' | |   / _ \\ / _ \\| \'_ ` _ \\ ');
  lines.push(' | |__| (_) | (_) | | | | | |');
  lines.push(' |_____\\___/ \\___/|_| |_| |_|');
  lines.push('  ' + VERSION + '');
  lines.push('');

  // Services status line
  var svcLine = '  Services: ';
  services.forEach(function(s) {
    svcLine += (s.active ? '[+]' : '[-]') + ' ' + s.label + '  ';
  });
  lines.push(svcLine.trim());

  // Active session
  if (activeSession) {
    lines.push('  Session:  Phase ' + activeSession.phase + ' | ' + activeSession.status + (activeSession.task ? ' | ' + activeSession.task : ''));
  }

  if (!workspaceOk) {
    lines.push('  Warning:  Hook state directory not writable');
  }

  lines.push('');
  lines.push('  Commands');
  lines.push('  /loom:craft .... Multi-agent pipeline    /loom:review ... Code review');
  lines.push('  /loom:agent .... Local Ollama agent       /loom:debug .... Investigation');
  lines.push('  /loom:status ... Session status           /loom:resume ... Resume session');
  lines.push('');
  lines.push('  36 Traits | 49 MCP Tools | 4 Archetypes | 684 Tests');
  lines.push('');

  var message = lines.join('\n');
  return { action: 'advisory', message: message, reason: null };
}

module.exports = { handleSessionStart };
