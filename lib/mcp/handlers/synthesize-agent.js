'use strict';

const fs = require('fs');
const path = require('path');
const { log } = require('../../core/logger');
const { parseFrontmatter } = require('./get-trait-index');

const MAX_PROMPT_CHARS = 32000;

function resolveTraitsDir() {
  const extensionRoot = process.env.LOOM_EXTENSION_PATH || process.env.CLAUDE_PLUGIN_ROOT;
  if (extensionRoot) return path.join(extensionRoot, 'traits');
  const serverFile = process.argv[1];
  if (serverFile) return path.join(path.dirname(serverFile), '..', 'traits');
  return path.join(process.cwd(), 'traits');
}

function loadFile(filePath) {
  const content = fs.readFileSync(filePath, 'utf8');
  const meta = parseFrontmatter(content);
  const bodyMatch = content.match(/^---\n[\s\S]*?\n---\n([\s\S]*)$/);
  const body = bodyMatch ? bodyMatch[1].trim() : '';
  return { meta, body };
}

function loadArchetype(traitsDir, archetypeName) {
  const filePath = path.join(traitsDir, 'archetypes', archetypeName + '.archetype.md');
  if (!fs.existsSync(filePath)) return null;
  return loadFile(filePath);
}

function loadTrait(traitsDir, traitName) {
  for (const subdir of ['capabilities', 'constraints', 'output-contracts']) {
    const filePath = path.join(traitsDir, subdir, traitName + '.trait.md');
    if (fs.existsSync(filePath)) return loadFile(filePath);
  }
  return null;
}

function validateInputs(traitsDir, params) {
  const errors = [];
  const warnings = [];

  const archetype = loadArchetype(traitsDir, params.archetype);
  if (!archetype) {
    return { archetype: null, loadedTraits: [], allTraitNames: new Set(), errors: ['Archetype not found: ' + params.archetype], warnings };
  }

  const loadedTraits = [];
  const allTraitNames = new Set(params.traits || []);

  for (const traitName of (params.traits || [])) {
    const trait = loadTrait(traitsDir, traitName);
    if (!trait) {
      errors.push('Trait not found: ' + traitName);
      continue;
    }
    if (trait.meta && trait.meta.archetypes && !trait.meta.archetypes.includes(params.archetype)) {
      warnings.push('Trait "' + traitName + '" is not designed for archetype "' + params.archetype + '" (compatible with: ' + (trait.meta.archetypes || []).join(', ') + ')');
    }
    loadedTraits.push({ name: traitName, meta: trait.meta, body: trait.body });
  }

  return { archetype, loadedTraits, allTraitNames, errors, warnings };
}

function checkConflicts(loadedTraits, allTraitNames) {
  const errors = [];
  for (const trait of loadedTraits) {
    const conflicts = (trait.meta && trait.meta.conflicts_with) || [];
    for (const conflict of conflicts) {
      if (allTraitNames.has(conflict)) {
        errors.push('Conflict: "' + trait.name + '" conflicts with "' + conflict + '"');
      }
    }
  }
  return errors;
}

function autoAddRequiredTraits(traitsDir, loadedTraits, allTraitNames) {
  const autoAdded = [];
  const warnings = [];
  const snapshot = [...loadedTraits];

  for (const trait of snapshot) {
    const requires = (trait.meta && trait.meta.requires) || [];
    for (const reqName of requires) {
      if (!allTraitNames.has(reqName)) {
        const reqTrait = loadTrait(traitsDir, reqName);
        if (reqTrait) {
          loadedTraits.push({ name: reqName, meta: reqTrait.meta, body: reqTrait.body });
          allTraitNames.add(reqName);
          autoAdded.push(reqName);
        } else {
          warnings.push('Required trait "' + reqName + '" (needed by "' + trait.name + '") not found');
        }
      }
    }
  }

  return { autoAdded, warnings };
}

function resolveTools(archetype, loadedTraits, archetypeName) {
  const errors = [];
  const archetypeAllowed = new Set(archetype.meta.allowed_tools || []);
  const archetypeForbidden = new Set(archetype.meta.forbidden_tools || []);
  const traitRequired = new Set();
  const traitForbidden = new Set();

  for (const trait of loadedTraits) {
    for (const tool of ((trait.meta && trait.meta.requires_tools) || [])) traitRequired.add(tool);
    for (const tool of ((trait.meta && trait.meta.forbids_tools) || [])) traitForbidden.add(tool);
  }

  for (const tool of traitRequired) {
    if (archetypeForbidden.has(tool)) {
      errors.push('Tool conflict: trait requires "' + tool + '" but archetype "' + archetypeName + '" forbids it');
    }
  }

  if (errors.length > 0) return { resolvedTools: [], errors };

  const resolvedTools = [];
  for (const tool of archetypeAllowed) {
    if (!traitForbidden.has(tool)) resolvedTools.push(tool);
  }
  for (const tool of traitRequired) {
    if (!traitForbidden.has(tool) && !archetypeAllowed.has(tool)) {
      resolvedTools.push(tool);
    }
  }

  return { resolvedTools, errors: [] };
}

function resolveBehavioralParams(archetype, loadedTraits, params) {
  const temps = loadedTraits.filter(function(t) { return t.meta && t.meta.temperature; }).map(function(t) { return t.meta.temperature; });
  var temperature = params.temperature_override ||
    (temps.length > 0 ? temps.reduce(function(a, b) { return a + b; }, 0) / temps.length : archetype.meta.default_temperature);
  const tRange = archetype.meta.temperature_range || [0.1, 0.5];
  temperature = Math.max(tRange[0], Math.min(tRange[1], temperature));

  const turns = loadedTraits.filter(function(t) { return t.meta && t.meta.max_turns; }).map(function(t) { return t.meta.max_turns; });
  var maxTurns = params.max_turns_override ||
    (turns.length > 0 ? Math.max.apply(null, turns) : archetype.meta.default_max_turns);
  const mRange = archetype.meta.max_turns_range || [5, 30];
  maxTurns = Math.max(mRange[0], Math.min(mRange[1], maxTurns));

  const timeouts = loadedTraits
    .filter(function(t) { return t.meta && t.meta.timeout_mins && t.meta.timeout_mins > 0; })
    .map(function(t) { return t.meta.timeout_mins; });
  const timeoutMins = timeouts.length > 0 ? Math.max.apply(null, timeouts) : (archetype.meta.timeout_mins || 10);

  return {
    temperature: Math.round(temperature * 100) / 100,
    maxTurns: maxTurns,
    timeoutMins: timeoutMins,
  };
}

function buildGroundingContext(params) {
  var groundingContext = '';
  var groundingApplied = [];

  if (params.detected_libraries && params.detected_libraries.length > 0) {
    groundingContext = '\n## Detected Libraries\nThe following libraries are in use: ' + params.detected_libraries.join(', ') + '. Consult their documentation for API details.\n';
    groundingApplied = params.detected_libraries;
  }
  if (params.grounding_queries && params.grounding_queries.length > 0) {
    groundingContext += '\n## Grounding Queries\nRelevant context queries: ' + params.grounding_queries.join('; ') + '\n';
  }

  return { groundingContext, groundingApplied };
}

function assemblePrompt(params, loadedTraits, autoAdded, resolvedTools, groundingContext) {
  const parts = [];
  const traitNames = params.traits || [];

  const agentName = 'synth-' + params.archetype + '-' + traitNames.slice(0, 3).join('-').substring(0, 40);
  parts.push('# Synthesized Agent: ' + agentName);
  parts.push('Archetype: ' + params.archetype);
  parts.push('Traits: ' + traitNames.join(', '));
  if (autoAdded.length > 0) {
    parts.push('Auto-loaded traits: ' + autoAdded.join(', '));
  }
  parts.push('');

  parts.push('## Available Tools');
  parts.push('You have access to ONLY these tools: ' + resolvedTools.join(', '));
  parts.push('Do NOT attempt to use any other tools.');
  parts.push('');

  if (params.archetype === 'builder') {
    parts.push('## File Writing Rules');
    parts.push('- Use write_file for new files. Use replace for modifications.');
    parts.push('- NEVER use run_shell_command with output redirection for file content.');
    parts.push('- Read the target file BEFORE modifying to understand existing patterns.');
    parts.push('');
  }

  for (const trait of loadedTraits) {
    if (trait.body) {
      parts.push('# ' + (trait.meta.name || trait.name) + ' Methodology');
      parts.push(trait.body);
      parts.push('');
    }
  }

  if (groundingContext) {
    parts.push(groundingContext);
  }

  if (params.task_context) {
    parts.push('## Task');
    parts.push(params.task_context);
    parts.push('');
  }

  const prompt = parts.join('\n');
  if (prompt.length > MAX_PROMPT_CHARS) {
    return { agentName, prompt: prompt.substring(0, MAX_PROMPT_CHARS) + '\n\n[Prompt truncated to fit token budget]' };
  }
  return { agentName, prompt };
}

function handleSynthesizeAgent(params) {
  const traitsDir = resolveTraitsDir();

  var result = validateInputs(traitsDir, params);
  if (result.errors.length > 0) {
    return { success: false, errors: result.errors, warnings: result.warnings };
  }

  var conflictErrors = checkConflicts(result.loadedTraits, result.allTraitNames);
  if (conflictErrors.length > 0) {
    return { success: false, errors: conflictErrors, warnings: result.warnings };
  }

  var autoResult = autoAddRequiredTraits(traitsDir, result.loadedTraits, result.allTraitNames);
  result.warnings = result.warnings.concat(autoResult.warnings);

  var toolResult = resolveTools(result.archetype, result.loadedTraits, params.archetype);
  if (toolResult.errors.length > 0) {
    return { success: false, errors: toolResult.errors, warnings: result.warnings };
  }

  var behavioral = resolveBehavioralParams(result.archetype, result.loadedTraits, params);
  var grounding = buildGroundingContext(params);
  var assembled = assemblePrompt(params, result.loadedTraits, autoResult.autoAdded, toolResult.resolvedTools, grounding.groundingContext);

  log('INFO', 'Synthesized agent: ' + assembled.agentName + ' (' + result.loadedTraits.length + ' traits, ' + toolResult.resolvedTools.length + ' tools)');

  return {
    success: true,
    agent_spec: {
      name: assembled.agentName,
      archetype: params.archetype,
      traits: params.traits || [],
      auto_added_traits: autoResult.autoAdded,
      tools: toolResult.resolvedTools,
      temperature: behavioral.temperature,
      max_turns: behavioral.maxTurns,
      timeout_mins: behavioral.timeoutMins,
      prompt: assembled.prompt,
      grounding_applied: grounding.groundingApplied,
    },
    warnings: result.warnings,
  };
}

module.exports = { handleSynthesizeAgent };
