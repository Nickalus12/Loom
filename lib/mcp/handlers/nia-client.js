'use strict';

const https = require('https');
const { URL } = require('url');
const { resolveSetting } = require('../../config/setting-resolver');
const { log } = require('../../core/logger');

const NIA_BASE_URL = 'https://apigcp.trynia.ai';
const NIA_TIMEOUT_MS = 15000;

function getNiaApiKey() {
  const key = resolveSetting('NIA_API_KEY');
  if (!key) return null;
  const enabled = resolveSetting('NIA_ENABLED');
  if (enabled === 'false') return null;
  return key;
}

function niaRequest(method, path, body) {
  return new Promise((resolve, reject) => {
    const apiKey = getNiaApiKey();
    if (!apiKey) {
      return reject(new Error('NIA_API_KEY not set'));
    }

    const url = new URL(path, NIA_BASE_URL);
    const payload = body ? JSON.stringify(body) : null;

    const options = {
      hostname: url.hostname,
      port: 443,
      path: url.pathname + url.search,
      method: method,
      headers: {
        'Authorization': `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      timeout: NIA_TIMEOUT_MS,
    };

    if (payload) {
      options.headers['Content-Length'] = Buffer.byteLength(payload);
    }

    const req = https.request(options, (res) => {
      const chunks = [];
      res.on('data', (chunk) => chunks.push(chunk));
      res.on('end', () => {
        const raw = Buffer.concat(chunks).toString('utf8');
        let parsed;
        try {
          parsed = JSON.parse(raw);
        } catch (_) {
          parsed = { raw_response: raw };
        }

        if (res.statusCode === 401 || res.statusCode === 403) {
          return reject(new Error(`Nia authentication failed (HTTP ${res.statusCode})`));
        }
        if (res.statusCode === 404) {
          return reject(new Error(`Nia resource not found (HTTP 404)`));
        }
        if (res.statusCode === 429) {
          return reject(new Error(`Nia rate limit exceeded (HTTP 429)`));
        }
        if (res.statusCode >= 400) {
          return reject(new Error(`Nia API error (HTTP ${res.statusCode}): ${parsed.message || raw}`));
        }

        resolve(parsed);
      });
    });

    req.on('timeout', () => {
      req.destroy();
      reject(new Error('Nia connection failed: request timed out'));
    });

    req.on('error', (err) => {
      reject(new Error(`Nia connection failed: ${err.message}`));
    });

    if (payload) {
      req.write(payload);
    }
    req.end();
  });
}

async function handleNiaListSources(params) {
  const apiKey = getNiaApiKey();
  if (!apiKey) {
    return { available: false, reason: 'NIA_API_KEY not set. Get a key at app.trynia.ai' };
  }

  try {
    const limit = params.limit || 20;
    const offset = params.offset || 0;
    const data = await niaRequest('GET', `/v2/sources?limit=${limit}&offset=${offset}`);

    return {
      available: true,
      sources: (data.items || []).map((item) => ({
        id: item.id,
        type: item.type,
        identifier: item.identifier,
        display_name: item.display_name,
        status: item.status,
        trust_level: (item.curation && item.curation.trust_signals && item.curation.trust_signals.trust_level) || 'unknown',
      })),
      total: (data.pagination && data.pagination.total) || 0,
    };
  } catch (err) {
    log('error', `nia_list_sources failed: ${err.message}`);
    return { available: true, error: err.message };
  }
}

async function handleNiaCheckRepoStatus(params) {
  const apiKey = getNiaApiKey();
  if (!apiKey) {
    return { available: false, reason: 'NIA_API_KEY not set' };
  }

  try {
    const repo = params.repository;
    if (!repo || !repo.includes('/')) {
      return { available: true, error: 'repository must be in owner/repo format' };
    }
    const [owner, name] = repo.split('/');
    const data = await niaRequest('GET', `/v2/repositories/${encodeURIComponent(owner)}/${encodeURIComponent(name)}`);

    return {
      available: true,
      repository: repo,
      status: data.status,
      progress: data.progress || null,
    };
  } catch (err) {
    log('error', `nia_check_repo_status failed: ${err.message}`);
    return { available: true, error: err.message };
  }
}

async function handleNiaSearch(params) {
  const apiKey = getNiaApiKey();
  if (!apiKey) {
    return { available: false, reason: 'NIA_API_KEY not set' };
  }

  try {
    const body = {
      query: params.query,
      repositories: params.repositories || [],
    };
    if (params.limit) {
      body.limit = params.limit;
    }

    const data = await niaRequest('POST', '/v2/universal-search', body);
    return { available: true, results: data };
  } catch (err) {
    log('error', `nia_search failed: ${err.message}`);
    return { available: true, error: err.message };
  }
}

async function handleNiaPackageSearch(params) {
  const apiKey = getNiaApiKey();
  if (!apiKey) {
    return { available: false, reason: 'NIA_API_KEY not set' };
  }

  try {
    const body = {
      registry: params.registry,
      package_name: params.package_name,
      semantic_queries: params.queries || [],
    };

    const data = await niaRequest('POST', '/v2/package-search/hybrid', body);
    return { available: true, results: data };
  } catch (err) {
    log('error', `nia_package_search failed: ${err.message}`);
    return { available: true, error: err.message };
  }
}

module.exports = {
  handleNiaListSources,
  handleNiaCheckRepoStatus,
  handleNiaSearch,
  handleNiaPackageSearch,
};
