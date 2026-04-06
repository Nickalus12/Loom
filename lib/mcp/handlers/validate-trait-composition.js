'use strict';

const fs = require('fs');
const path = require('path');
const { parseFrontmatter } = require('./get-trait-index');
const { log } = require('../../core/logger');

function resolveTraitsDir() {
  const extensionRoot = process.env.LOOM_EXTENSION_PATH || process.env.CLAUDE_PLUGIN_ROOT;
  if (extensionRoot) return path.join(extensionRoot, 'traits');
  const serverFile = process.argv[1];
  if (serverFile) return path.join(path.dirname(serverFile), '..', 'traits');
  return path.join(process.cwd(), 'traits');
}

function loadMeta(traitsDir, name, type) {
  const subdirs = type === 'archetype' ? ['archetypes'] : ['capabilities', 'constraints', 'output-contracts'];
  const ext = type === 'archetype' ? '.archetype.md' : '.trait.md';
  for (const subdir of subdirs) {
    const fp = path.join(traitsDir, subdir, name + ext);
    if (fs.existsSync(fp)) {
      const content = fs.readFileSync(fp, 'utf8');
      return parseFrontmatter(content);
    }
  }
  return null;
}

function handleValidateTraitComposition(params) {
  const traitsDir = resolveTraitsDir();
  const errors = [];
  const warnings = [];
  const autoAddedTraits = [];

  const archetypeMeta = loadMeta(traitsDir, params.archetype, 'archetype');
  if (!archetypeMeta) {
    return { valid: false, errors: ['Archetype not found: ' + params.archetype], warnings: [], auto_added_traits: [], resolved_tools: [] };
  }

  const allTraitNames = new Set(params.traits || []);
  const traitMetas = [];

  for (const name of (params.traits || [])) {
    const meta = loadMeta(traitsDir, name, 'trait');
    if (!meta) {
      errors.push('Trait not found: ' + name);
      continue;
    }
    if (meta.archetypes && !meta.archetypes.includes(params.archetype)) {
      warnings.push('Trait "' + name + '" not designed for archetype "' + params.archetype + '"');
    }
    traitMetas.push({ name: name, meta: meta });
  }

  for (var i = 0; i < traitMetas.length; i++) {
    var entry = traitMetas[i];
    var conflicts = (entry.meta && entry.meta.conflicts_with) || [];
    for (var j = 0; j < conflicts.length; j++) {
      if (allTraitNames.has(conflicts[j])) {
        errors.push('Conflict: "' + entry.name + '" conflicts with "' + conflicts[j] + '"');
      }
    }
  }

  var snapshot = traitMetas.slice();
  for (var k = 0; k < snapshot.length; k++) {
    var requires = (snapshot[k].meta && snapshot[k].meta.requires) || [];
    for (var m = 0; m < requires.length; m++) {
      var req = requires[m];
      if (!allTraitNames.has(req)) {
        var reqMeta = loadMeta(traitsDir, req, 'trait');
        if (reqMeta) {
          allTraitNames.add(req);
          autoAddedTraits.push(req);
          traitMetas.push({ name: req, meta: reqMeta });
        } else {
          warnings.push('Required trait "' + req + '" not found');
        }
      }
    }
  }

  var archetypeAllowed = new Set(archetypeMeta.allowed_tools || []);
  var archetypeForbidden = new Set(archetypeMeta.forbidden_tools || []);
  var resolvedTools = new Set(archetypeAllowed);

  for (var n = 0; n < traitMetas.length; n++) {
    var traitMeta = traitMetas[n].meta;
    var reqTools = (traitMeta && traitMeta.requires_tools) || [];
    for (var p = 0; p < reqTools.length; p++) {
      if (archetypeForbidden.has(reqTools[p])) {
        errors.push('Tool conflict: trait requires "' + reqTools[p] + '" but archetype forbids it');
      } else {
        resolvedTools.add(reqTools[p]);
      }
    }
    var forbTools = (traitMeta && traitMeta.forbids_tools) || [];
    for (var q = 0; q < forbTools.length; q++) {
      resolvedTools.delete(forbTools[q]);
    }
  }

  log('INFO', 'Validated trait composition: archetype=' + params.archetype + ', traits=' + (params.traits || []).join(',') + ', valid=' + (errors.length === 0));

  return {
    valid: errors.length === 0,
    errors: errors,
    warnings: warnings,
    auto_added_traits: autoAddedTraits,
    resolved_tools: Array.from(resolvedTools),
  };
}

module.exports = { handleValidateTraitComposition };
