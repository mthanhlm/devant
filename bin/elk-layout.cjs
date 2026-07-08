#!/usr/bin/env node
'use strict';
// elkjs driver for `devant layout`: JSON in (stdin), JSON out (stdout). No XML here —
// bin/devant owns all mxGraph parsing (con-stdlib); this script only runs the ELK algorithms.
// CommonJS on purpose: require() honors NODE_PATH, which bin/devant points at `npm root -g`
// so the globally-installed elkjs resolves (ESM import would ignore NODE_PATH).
let ELK;
try {
  ELK = require('elkjs');
} catch (e) {
  process.stderr.write('elkjs not found — run: npm i -g elkjs\n');
  process.exit(3);
}

// Cycle-breaking + model-order hints (dec-041): activity flows legitimately carry loop
// back-edges; without these, ELK's greedy cycle breaking may reverse forward edges and
// scramble the narrative order the caller authored the nodes/edges in.
const LAYERED_ORDER = {
  'elk.layered.cycleBreaking.strategy': 'GREEDY_MODEL_ORDER',
  'elk.layered.considerModelOrder.strategy': 'NODES_AND_EDGES',
};

const PRESETS = {
  verticalFlow:   Object.assign({ 'elk.algorithm': 'layered', 'elk.direction': 'DOWN' }, LAYERED_ORDER),
  horizontalFlow: Object.assign({ 'elk.algorithm': 'layered', 'elk.direction': 'RIGHT' }, LAYERED_ORDER),
  verticalTree:   { 'elk.algorithm': 'mrtree', 'elk.direction': 'DOWN' },
  horizontalTree: { 'elk.algorithm': 'mrtree', 'elk.direction': 'RIGHT' },
  radialTree:     { 'elk.algorithm': 'radial' },
  organic:        { 'elk.algorithm': 'force' },
};

let raw = '';
process.stdin.on('data', (c) => { raw += c; });
process.stdin.on('end', () => {
  let req;
  try {
    req = JSON.parse(raw);
  } catch (e) {
    process.stderr.write('bad input JSON: ' + e.message + '\n');
    process.exit(2);
  }
  const opts = PRESETS[req.preset];
  if (!opts) {
    process.stderr.write('unknown preset: ' + req.preset + '\n');
    process.exit(2);
  }
  const graph = {
    id: '__root__',
    layoutOptions: Object.assign({
      'elk.spacing.nodeNode': '40',
      'elk.layered.spacing.nodeNodeBetweenLayers': '60',
      'elk.spacing.edgeNode': '25',
    }, opts),
    children: req.nodes.map((n) => ({ id: n.id, width: n.width, height: n.height })),
    // e.label ({text,width,height}, metrics computed by the Python caller) makes ELK reserve
    // inter-layer space for the label; ELK's own label positions are discarded (only node
    // positions flow back), so this never fights draw.io's label placement.
    edges: req.edges.map((e, i) => ({
      id: '__e' + i, sources: [e.source], targets: [e.target],
      labels: e.label ? [e.label] : undefined,
    })),
  };
  new ELK().layout(graph).then((res) => {
    const positions = {};
    for (const c of res.children || []) positions[c.id] = { x: c.x, y: c.y };
    process.stdout.write(JSON.stringify({ positions: positions }));
  }).catch((err) => {
    process.stderr.write('elk layout failed: ' + (err && err.message ? err.message : err) + '\n');
    process.exit(1);
  });
});
