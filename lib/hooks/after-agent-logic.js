'use strict';

const { log } = require('../core/logger');
const hookState = require('./hook-state');

const TASK_REPORT_REQUIRED_FIELDS = ['Status', 'Files Created', 'Files Modified'];

const GIVE_UP_PATTERNS = [
  /\bi\s+(?:don'?t|do\s+not)\s+know\b/i,
  /\bi\s+cannot\b/i,
  /\bi\s+can'?t\b/i,
  /\bi'?m\s+unable\s+to\b/i,
  /\bi\s+(?:was|am)\s+not\s+able\s+to\b/i,
  /\bthis\s+is\s+beyond\s+my\b/i,
  /\bi\s+(?:don'?t|do\s+not)\s+have\s+(?:access|the\s+ability)\b/i,
];

function extractTaskReportSection(text) {
  const match = text.match(/##?\s*Task Report\s*\n([\s\S]*?)(?:\n##?\s|\n---|\s*$)/);
  return match ? match[1] : '';
}

function extractFileList(section, fieldName) {
  const pattern = new RegExp(
    `\\*\\*${fieldName}\\*\\*:\\s*(.+?)(?=\\n\\*\\*|\\n##|$)`,
    's'
  );
  const match = section.match(pattern);
  if (!match) return [];
  const raw = match[1].trim();
  if (/^[\["]?none[\]"]?$/i.test(raw) || raw === '-' || raw === 'N/A') return [];

  const files = [];
  const lines = raw.split('\n');
  for (const line of lines) {
    const pathMatch = line.match(/[`"]?([^\s`"*,]+\.[a-zA-Z0-9]+)/);
    if (pathMatch) {
      files.push(pathMatch[1]);
    }
  }
  return files;
}

function validateTaskReportFields(taskReportSection) {
  const missing = [];
  for (const field of TASK_REPORT_REQUIRED_FIELDS) {
    const pattern = new RegExp(`\\*\\*${field}\\*\\*:`, 'i');
    if (!pattern.test(taskReportSection)) {
      missing.push(field);
    }
  }
  return missing;
}

function detectGiveUpPatterns(text) {
  if (!text || text.length > 200) return false;
  return GIVE_UP_PATTERNS.some((p) => p.test(text));
}

/**
 * After-agent hook logic (runtime-agnostic).
 *
 * Field name mapping: the Gemini adapter maps ctx.promptResponse -> ctx.agentResult
 * before calling this function.
 *
 * @param {object} ctx - Internal context contract
 * @param {string} ctx.sessionId
 * @param {string|null} ctx.agentResult  - the agent response text
 * @param {boolean} ctx.stopHookActive
 * @returns {{ action: string, message: null, reason: string|null }}
 */
function handleAfterAgent(ctx) {
  const agentName = hookState.getActiveAgent(ctx.sessionId);
  if (!agentName) {
    hookState.clearActiveAgent(ctx.sessionId);
    return { action: 'allow', message: null, reason: null };
  }

  const agentResult = ctx.agentResult || '';

  const dispatchTs = hookState.getTimestamp(ctx.sessionId, `dispatch-${agentName}`);
  const durationMs = dispatchTs > 0 ? Date.now() - dispatchTs : 0;
  const durationSec = Math.round(durationMs / 1000);

  if (!agentResult.trim()) {
    log('WARN', `AfterAgent [${agentName}]: Empty response detected (duration: ${durationSec}s)`);
    recordCompletionTelemetry(ctx.sessionId, agentName, durationMs, 'empty_response', []);
    hookState.clearActiveAgent(ctx.sessionId);
    if (!ctx.stopHookActive) {
      return {
        action: 'deny',
        message: null,
        reason: 'Agent returned an empty response. Please provide a complete response with a ## Task Report and ## Downstream Context section.',
      };
    }
    return { action: 'allow', message: null, reason: null };
  }

  if (agentResult.length < 200 && detectGiveUpPatterns(agentResult)) {
    log('WARN', `AfterAgent [${agentName}]: Agent appears to have given up: "${agentResult.slice(0, 100)}"`);
  }

  const hasTaskReport = agentResult.includes('## Task Report') || agentResult.includes('# Task Report');
  const hasDownstream = agentResult.includes('## Downstream Context') || agentResult.includes('# Downstream Context');

  const warnings = [];
  if (!hasTaskReport) warnings.push('Missing Task Report section (expected ## Task Report heading)');
  if (!hasDownstream) warnings.push('Missing Downstream Context section (expected ## Downstream Context heading)');

  if (hasTaskReport) {
    const taskReportContent = extractTaskReportSection(agentResult);
    const missingFields = validateTaskReportFields(taskReportContent);
    if (missingFields.length > 0) {
      warnings.push(`Task Report missing required fields: ${missingFields.join(', ')}`);
    }

    const filesCreated = extractFileList(taskReportContent, 'Files Created');
    const filesModified = extractFileList(taskReportContent, 'Files Modified');
    const allFiles = [...filesCreated, ...filesModified];

    if (allFiles.length > 0) {
      hookState.storeJson(ctx.sessionId, `manifest-${agentName}`, {
        agent: agentName,
        filesCreated,
        filesModified,
        timestamp: Date.now(),
      });
      log('INFO', `AfterAgent [${agentName}]: Extracted file manifest (${filesCreated.length} created, ${filesModified.length} modified)`);
    }

    recordCompletionTelemetry(ctx.sessionId, agentName, durationMs, 'completed', allFiles);
  } else {
    recordCompletionTelemetry(ctx.sessionId, agentName, durationMs, 'malformed', []);
  }

  if (warnings.length > 0) {
    const reason = warnings.join('; ');
    if (ctx.stopHookActive) {
      log('WARN', `AfterAgent [${agentName}]: Retry still malformed: ${reason} -- allowing to prevent infinite loop`);
    } else {
      log('WARN', `AfterAgent [${agentName}]: WARN: ${reason} -- requesting retry`);
      hookState.clearActiveAgent(ctx.sessionId);
      return {
        action: 'deny',
        message: null,
        reason: `Handoff report validation failed: ${reason}. Please include both a ## Task Report section and a ## Downstream Context section in your response.`,
      };
    }
  } else {
    log('INFO', `AfterAgent [${agentName}]: Handoff report validated (duration: ${durationSec}s)`);
  }

  hookState.clearActiveAgent(ctx.sessionId);
  return { action: 'allow', message: null, reason: null };
}

function recordCompletionTelemetry(sessionId, agentName, durationMs, outcome, files) {
  try {
    hookState.incrementCounter(sessionId, 'agent-completions');
    hookState.appendToList(sessionId, 'agent-stats', {
      agent: agentName,
      durationMs,
      outcome,
      filesChanged: files.length,
      timestamp: Date.now(),
    });
  } catch (err) {
    log('DEBUG', `AfterAgent: Failed to record telemetry: ${err.message}`);
  }
}

module.exports = { handleAfterAgent };
