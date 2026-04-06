'use strict';

/**
 * Loom file guard for Claude Code.
 * PreToolUse hook for Write|Edit — warns on sensitive files but doesn't block.
 * The user always has final say.
 */

const { readBoundedStdin } = require('./hook-adapter');

const SENSITIVE_PATTERNS = [
  /\.env$/i,
  /\.env\.\w+$/i,
  /credentials/i,
  /\.key$/i,
  /\.pem$/i,
  /\.crt$/i,
  /\.p12$/i,
  /\.pfx$/i,
  /\.ssh\//i,
  /id_rsa/i,
  /id_ed25519/i,
  /\.gnupg\//i,
  /token\.json$/i,
  /\.htpasswd$/i,
];

readBoundedStdin()
  .then((raw) => {
    const filePath = raw.tool_input?.file_path || raw.tool_input?.path || '';

    if (!filePath) {
      process.stdout.write(JSON.stringify({ decision: 'approve' }) + '\n');
      return;
    }

    const isSensitive = SENSITIVE_PATTERNS.some((pattern) => pattern.test(filePath));

    if (isSensitive) {
      // Warn but don't block — user has final say via Claude Code's permission prompt
      process.stderr.write('[file-guard] Sensitive file detected: ' + filePath + '\n');
      process.stdout.write(JSON.stringify({
        decision: 'approve',
        systemMessage: 'Note: ' + filePath + ' is a sensitive file (credentials/keys/env). Proceed with caution.',
      }) + '\n');
    } else {
      process.stdout.write(JSON.stringify({ decision: 'approve' }) + '\n');
    }
  })
  .catch((err) => {
    process.stderr.write('File guard error: ' + err.message + '\n');
    process.stdout.write(JSON.stringify({ decision: 'approve' }) + '\n');
  });
