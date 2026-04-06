'use strict';

const LOG_LEVELS = { DEBUG: 0, INFO: 1, WARN: 2, ERROR: 3 };
const _minLevel = LOG_LEVELS[process.env.LOOM_LOG_LEVEL?.toUpperCase()] ?? LOG_LEVELS.INFO;

function _timestamp() {
  return new Date().toISOString().slice(11, 23);
}

function log(level, message) {
  const numLevel = LOG_LEVELS[level.toUpperCase()] ?? LOG_LEVELS.INFO;
  if (numLevel < _minLevel) return;
  process.stderr.write(`[${_timestamp()}] [${level.toUpperCase()}] loom: ${message}\n`);
}

function debug(message) { log('DEBUG', message); }
function info(message) { log('INFO', message); }
function warn(message) { log('WARN', message); }
function error(message) { log('ERROR', message); }

function fatal(message) {
  process.stderr.write(`[${_timestamp()}] [FATAL] loom: ${message}\n`);
  process.exit(1);
}

module.exports = { log, debug, info, warn, error, fatal, LOG_LEVELS };
