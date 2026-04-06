'use strict';

const fs = require('fs');
const path = require('path');
const yaml = require('js-yaml');
const { log } = require('../../core/logger');

let _cache = null;
let _cacheTime = 0;
const CACHE_TTL_MS = 5 * 60 * 1000;

function resolveTraitsDir() {
  const extensionRoot = process.env.LOOM_EXTENSION_PATH || process.env.CLAUDE_PLUGIN_ROOT;
  if (extensionRoot) return path.join(extensionRoot, 'traits');
  const serverFile = process.argv[1];
  if (serverFile) return path.join(path.dirname(serverFile), '..', 'traits');
  return path.join(process.cwd(), 'traits');
}

function parseFrontmatter(content) {
  const match = content.match(/^---\n([\s\S]*?)\n---/);
  if (!match) return null;
  try {
    return yaml.load(match[1]);
  } catch (e) {
    return null;
  }
}

function scanTraits(traitsDir) {
  const results = [];
  const categories = ['archetypes', 'capabilities', 'constraints', 'output-contracts'];

  for (const category of categories) {
    const dir = path.join(traitsDir, category);
    if (!fs.existsSync(dir)) continue;

    const files = fs.readdirSync(dir).filter(f => f.endsWith('.trait.md') || f.endsWith('.archetype.md'));
    for (const file of files) {
      const content = fs.readFileSync(path.join(dir, file), 'utf8');
      const meta = parseFrontmatter(content);
      if (!meta) continue;

      const isArchetype = file.endsWith('.archetype.md');
      results.push({
        name: meta.name,
        category: isArchetype ? 'archetype' : (meta.category || category),
        description: meta.description || '',
        archetypes: meta.archetypes || [],
        compatible_with: meta.compatible_with || [],
        conflicts_with: meta.conflicts_with || [],
        requires: meta.requires || [],
        requires_tools: meta.requires_tools || meta.allowed_tools || [],
        forbids_tools: meta.forbids_tools || meta.forbidden_tools || [],
        grounding_categories: meta.grounding_categories || [],
        grounding_priority: meta.grounding_priority || 'low',
        ...(isArchetype ? {
          allowed_tools: meta.allowed_tools || [],
          forbidden_tools: meta.forbidden_tools || [],
          temperature_range: meta.temperature_range || [0.1, 0.5],
          default_temperature: meta.default_temperature || 0.3,
          max_turns_range: meta.max_turns_range || [5, 25],
          default_max_turns: meta.default_max_turns || 15,
        } : {}),
      });
    }
  }

  return results;
}

function handleGetTraitIndex(params) {
  const now = Date.now();
  if (!_cache || (now - _cacheTime) > CACHE_TTL_MS) {
    const traitsDir = resolveTraitsDir();
    _cache = scanTraits(traitsDir);
    _cacheTime = now;
    log('INFO', 'Trait index rebuilt: ' + _cache.length + ' entries');
  }

  let results = _cache;

  if (params.category && params.category !== 'all') {
    results = results.filter(t => t.category === params.category);
  }

  if (params.archetype) {
    results = results.filter(t =>
      t.category === 'archetype' ||
      (t.archetypes && t.archetypes.includes(params.archetype))
    );
  }

  return { traits: results, total: results.length };
}

module.exports = { handleGetTraitIndex, scanTraits, parseFrontmatter };
