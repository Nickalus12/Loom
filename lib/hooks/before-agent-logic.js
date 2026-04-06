'use strict';

const fs = require('fs');
const { log } = require('../core/logger');
const { detectAgentFromPrompt, getAgentCapability } = require('../core/agent-registry');
const { validateSessionId } = require('../state/session-id-validator');
const { resolveSetting } = require('../config/setting-resolver');
const hookState = require('./hook-state');
const state = require('../state/session-state');

const WRITE_INDICATORS = [
  'write', 'create', 'generate', 'implement', 'build',
  'add file', 'new file', 'scaffold', 'initialize',
];

const SHELL_INDICATORS = [
  'run', 'execute', 'shell', 'bash', 'terminal',
  'npm', 'yarn', 'pip', 'docker', 'make',
];

function promptImpliesWriting(prompt) {
  if (!prompt) return false;
  const lower = prompt.toLowerCase();
  return WRITE_INDICATORS.some((w) => lower.includes(w));
}

function promptImpliesShell(prompt) {
  if (!prompt) return false;
  const lower = prompt.toLowerCase();
  return SHELL_INDICATORS.some((w) => lower.includes(w));
}

/**
 * Before-agent hook logic (runtime-agnostic).
 *
 * Field name mapping: the Gemini adapter maps ctx.prompt -> ctx.agentInput
 * before calling this function.
 *
 * @param {object} ctx - Internal context contract
 * @param {string} ctx.sessionId
 * @param {string} ctx.cwd
 * @param {string|null} ctx.agentInput  - the agent prompt text
 * @param {string} [ctx.event]          - hook event name (used in context message)
 * @returns {{ action: string, message: string|null, reason: string|null }}
 */
function handleBeforeAgent(ctx) {
  hookState.pruneStale();

  const agentName = detectAgentFromPrompt(ctx.agentInput);

  if (agentName && validateSessionId(ctx.sessionId)) {
    hookState.setActiveAgent(ctx.sessionId, agentName);
    hookState.setTimestamp(ctx.sessionId, `dispatch-${agentName}`);
    hookState.incrementCounter(ctx.sessionId, 'agent-dispatches');
    log('INFO', `BeforeAgent: Detected agent '${agentName}' -- set active agent [session=${ctx.sessionId}]`);
  }

  if (agentName) {
    const disabledRaw = resolveSetting('LOOM_DISABLED_AGENTS', ctx.cwd) || '';
    const disabledList = disabledRaw
      .split(',')
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean);
    if (disabledList.includes(agentName.toLowerCase())) {
      log('WARN', `BeforeAgent: Agent '${agentName}' is disabled via LOOM_DISABLED_AGENTS`);
      return { action: 'deny', reason: 'Agent disabled via LOOM_DISABLED_AGENTS' };
    }
  }

  if (agentName) {
    const capability = getAgentCapability(agentName);
    if (capability === 'read_only' && promptImpliesWriting(ctx.agentInput)) {
      log('WARN', `BeforeAgent: Agent '${agentName}' has read_only capability but prompt implies file writing`);
      return {
        action: 'deny',
        reason: `Agent '${agentName}' has read_only capability and cannot perform file-writing tasks. Dispatch a read_write or full capability agent instead.`,
      };
    }
    if (capability === 'read_only' && promptImpliesShell(ctx.agentInput)) {
      log('WARN', `BeforeAgent: Agent '${agentName}' has read_only capability but prompt implies shell execution`);
      return {
        action: 'deny',
        reason: `Agent '${agentName}' has read_only capability and cannot execute shell commands. Dispatch a read_shell or full capability agent instead.`,
      };
    }
  }

  const messageParts = [];

  const sessionPath = state.resolveActiveSessionPath(ctx.cwd);
  try {
    const content = fs.readFileSync(sessionPath, 'utf8');
    const parts = [];
    const phaseMatch = content.match(/current_phase:\s*(\S+)/);
    if (phaseMatch) parts.push(`current_phase=${phaseMatch[1]}`);
    const statusMatch = content.match(/status:\s*(\S+)/);
    if (statusMatch) parts.push(`status=${statusMatch[1]}`);

    const completedMatch = content.match(/completed_phases:\s*\[([^\]]*)\]/);
    if (completedMatch && completedMatch[1].trim()) {
      parts.push(`completed_phases=[${completedMatch[1].trim()}]`);
    }

    if (parts.length > 0) {
      messageParts.push(`Active session: ${parts.join(', ')}`);
    }

    const downstreamMatch = content.match(/## Downstream Context\s*\n([\s\S]*?)(?:\n##|\n---|\Z)/);
    if (downstreamMatch && downstreamMatch[1].trim()) {
      const downstream = downstreamMatch[1].trim();
      if (downstream.length <= 500) {
        messageParts.push(`Downstream context from previous phase:\n${downstream}`);
      }
    }
  } catch {}

  if (agentName) {
    const capability = getAgentCapability(agentName) || 'unknown';
    messageParts.push(`Agent: ${agentName} (capability: ${capability})`);
  }

  const message = messageParts.length > 0 ? messageParts.join('\n') : null;
  return { action: 'allow', message, reason: null };
}

module.exports = { handleBeforeAgent };
