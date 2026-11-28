#!/usr/bin/env node
// Render the README diagrams to static SVG files in doc/diagrams/.
// GitHub shows a README image but runs no script and loads no stylesheet, so each
// SVG carries its own <style> and a white background (readable in dark mode too).
// The diagrams are data (boxes on a grid, labelled edges); edit the specs below and
// re-run instead of editing the SVG files.
// Usage: node scripts/diagrams.mjs        (writes doc/diagrams/*.svg)
// ponytail: boxDiagram is copied from the tw-html-explainer skill; it does not route
// edges around boxes, so node placement must keep every edge clear.
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "doc", "diagrams");

const C = {
  ink: "#1f2328", muted: "#59636e", line: "#d1d9e0", subtle: "#f6f8fa",
  accent: "#0969da", success: "#1a7f37", danger: "#d1242f", attention: "#9a6700",
  neutral: "#818b98",
};
const SANS = '-apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif';
const MONO = 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace';
const STYLE = `
text { font-family: ${SANS}; }
.n rect { fill: #fff; stroke: ${C.neutral}; stroke-width: 1.5; }
.n.accent rect { stroke: ${C.accent}; } .n.success rect { stroke: ${C.success}; }
.n.danger rect { stroke: ${C.danger}; } .n.attention rect { stroke: ${C.attention}; }
.n.muted rect { stroke: ${C.line}; stroke-dasharray: 4 3; }
.n text { font-size: 13px; font-weight: 600; fill: ${C.ink}; }
.n text.sub { font-size: 11px; font-weight: 400; fill: ${C.muted}; }
.n text.ln { font-size: 11.5px; font-weight: 400; fill: ${C.ink}; }
.mono { font-family: ${MONO}; font-weight: 400; }
.e { fill: none; stroke: ${C.neutral}; stroke-width: 1.5; }
.e.dashed { stroke-dasharray: 5 4; } .e.strong { stroke-width: 2.5; }
.e.accent { stroke: ${C.accent}; } .e.success { stroke: ${C.success}; }
.e.danger { stroke: ${C.danger}; } .e.attention { stroke: ${C.attention}; }
.el { font-size: 11px; fill: ${C.muted}; paint-order: stroke; stroke: #fff; stroke-width: 4px; stroke-linejoin: round; }
.lg { font-size: 12px; fill: ${C.muted}; }
.grp rect { fill: ${C.subtle}; stroke: ${C.line}; stroke-dasharray: 6 4; }
.grp text { font-size: 12px; font-weight: 600; fill: ${C.muted}; }
`;

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;");

function markers(p) {
  const c = { neutral: C.neutral, accent: C.accent, success: C.success, danger: C.danger, attention: C.attention };
  return "<defs>" + Object.entries(c).map(([k, v]) =>
    `<marker id="${p}-${k}" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="10" markerHeight="10" orient="auto">` +
    `<path d="M0,0 L10,5 L0,10 z" fill="${v}"/></marker>`).join("") + "</defs>";
}

// Copied from the tw-html-explainer skill (assets/skeleton.html), returning the SVG
// string instead of writing innerHTML. Spec format is documented there.
function boxDiagram(p, spec) {
  const CW = spec.cellW || 220, CH = spec.cellH || 110, BW = spec.boxW || 150, BH = 52, LH = 16;
  const at = {};
  for (const n of spec.nodes) {
    const h = n.lines ? 32 + (n.sub ? LH : 0) + n.lines.length * LH : BH;
    at[n.id] = { x: n.col * CW + CW / 2, y: n.row * CH + CH / 2, w: n.w || BW, h, n };
  }
  const exit = (a, tx, ty) => {
    const hw = a.w / 2 + 3, hh = a.h / 2 + 3, dx = tx - a.x, dy = ty - a.y;
    const t = Math.min(dx ? hw / Math.abs(dx) : Infinity, dy ? hh / Math.abs(dy) : Infinity);
    return [a.x + dx * t, a.y + dy * t];
  };
  const ecls = (e) => `e ${e.kind || ""}${e.dashed ? " dashed" : ""}${e.strong ? " strong" : ""}`;
  const mono = (s) => esc(s).replace(/`([^`]+)`/g, '<tspan class="mono">$1</tspan>');
  let back = "", lines = "", boxes = "", labels = "", top = 0;
  for (const gr of spec.groups || []) {
    const pd = gr.pad || 0, x = gr.cols[0] * CW + 6 + pd, y = gr.rows[0] * CH + 4 + pd;
    const w = (gr.cols[1] - gr.cols[0] + 1) * CW - 12 - 2 * pd, h = (gr.rows[1] - gr.rows[0] + 1) * CH - 8 - 2 * pd;
    back += `<g class="grp"><rect x="${x}" y="${y}" width="${w}" height="${h}" rx="8"/><text x="${x + 10}" y="${y + 16}">${mono(gr.label)}</text></g>`;
  }
  for (const e of spec.edges) {
    const a = at[e.from], b = at[e.to], mk = `marker-end="url(#${p}-${e.kind || "neutral"})"`;
    let d, lx, ly, anchor = "middle";
    if (e.route) {
      const hv = e.route === "hv", cx = hv ? b.x : a.x, cy = hv ? a.y : b.y;
      const s = hv ? [a.x + Math.sign(b.x - a.x) * (a.w / 2 + 3), a.y] : [a.x, a.y + Math.sign(b.y - a.y) * (a.h / 2 + 3)];
      const t = hv ? [b.x, b.y - Math.sign(b.y - a.y) * (b.h / 2 + 3)] : [b.x - Math.sign(b.x - a.x) * (b.w / 2 + 3), b.y];
      d = `M${s} L${cx},${cy} L${t}`;
      const [p1, p2] = Math.hypot(cx - s[0], cy - s[1]) >= Math.hypot(t[0] - cx, t[1] - cy) ? [s, [cx, cy]] : [[cx, cy], t];
      if (p1[1] === p2[1]) { lx = (p1[0] + p2[0]) / 2; ly = p1[1] - 6; }
      else { lx = p1[0] + 6; ly = (p1[1] + p2[1]) / 2 + 4; anchor = "start"; }
    } else {
      const len = Math.hypot(b.x - a.x, b.y - a.y), k = (e.bend || 0) / len;
      const qx = (a.x + b.x) / 2 + (b.y - a.y) * k, qy = (a.y + b.y) / 2 - (b.x - a.x) * k;
      const [sx, sy] = exit(a, qx, qy), [ex, ey] = exit(b, qx, qy);
      d = `M${sx},${sy} Q${qx},${qy} ${ex},${ey}`;
      const mx = (sx + 2 * qx + ex) / 4, my = (sy + 2 * qy + ey) / 4, dx = ex - sx, dy = ey - sy;
      if (Math.abs(dy) <= Math.abs(dx) * 0.2) {
        const half = (e.label || "").replace(/`/g, "").length * 3.25;
        lx = mx; ly = my - 5 - Math.abs(dy / dx) * half;
      } else {
        const nx = dy / Math.hypot(dx, dy), ny = -dx / Math.hypot(dx, dy);
        lx = mx + nx * 8; ly = my + ny * 8 + 4; anchor = nx > 0 ? "start" : "end";
      }
    }
    lines += `<path class="${ecls(e)}" d="${d}" ${mk}/>`;
    if (e.label) labels += `<text class="el" x="${lx}" y="${ly}" text-anchor="${anchor}">${mono(e.label)}</text>`;
  }
  for (const { x, y, w, h, n } of Object.values(at)) {
    let txt;
    if (n.lines) {
      const x0 = x - w / 2 + 12;
      const rows = [["", n.label], ...(n.sub ? [[' class="sub"', n.sub]] : []), ...n.lines.map((l) => [' class="ln"', l])];
      txt = rows.map(([c, s], i) => `<text${c} x="${x0}" y="${y - h / 2 + 21 + i * LH}">${mono(s)}</text>`).join("");
    } else {
      const t = (dy, cls, s) => `<text${cls} x="${x}" y="${y + dy}" text-anchor="middle">${mono(s)}</text>`;
      txt = n.sub ? t(-3, "", n.label) + t(13, ' class="sub"', n.sub) : t(5, "", n.label);
    }
    boxes += `<g class="n ${n.kind || ""}"><rect x="${x - w / 2}" y="${y - h / 2}" width="${w}" height="${h}" rx="6"/>${txt}</g>`;
  }
  let legend = "";
  if (spec.legend) {
    const ly = top - 18;
    let lx = 12;
    for (const l of spec.legend) {
      legend += `<line class="${ecls(l)}" x1="${lx}" x2="${lx + 32}" y1="${ly}" y2="${ly}"/><text class="lg" x="${lx + 40}" y="${ly + 4}">${esc(l.text)}</text>`;
      lx += 64 + l.text.length * 6.5;
    }
    top = ly - 18;
  }
  const W = spec.cols * CW, H = spec.rows * CH - top;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 ${top} ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${esc(spec.title)}">` +
    `<title>${esc(spec.title)}</title><style>${STYLE}</style>` +
    `<rect x="0" y="${top}" width="${W}" height="${H}" fill="#fff"/>` +
    markers(p) + back + lines + boxes + labels + legend + "</svg>\n";
}

// Encoding, shared by every diagram:
//   accent box = twsrt itself; dashed grey box = outside twsrt (runtime, agents)
//   solid grey edge = twsrt compiles or writes; dashed grey edge = read at runtime
//   dashed accent edge = a read-only twsrt check
//   success edge = enforced by the kernel sandbox; attention edge = agent permissions only
const DIAGRAMS = {
  // Question: what do I edit, and which files does twsrt write from it?
  why: {
    title: "One policy, compiled into every agent's native configuration",
    cols: 3, rows: 5, cellW: 266, cellH: 88, boxW: 220,
    nodes: [
      { id: "frag", label: "Policy fragments", sub: "you edit", lines: ["`srt/*.jsonc`: paths, domains", "`bash/*.jsonc`: commands"], col: 0, row: 1.35 },
      { id: "conf", label: "config.toml", sub: "you edit", lines: ["profiles: which fragments", "targets: which agents"], col: 0, row: 2.65 },
      { id: "gen", label: "twsrt generate -w", sub: "compile + translate", col: 1, row: 2, kind: "accent", w: 170 },
      { id: "srt", label: "srt sandbox", lines: ["`~/.srt-settings.json`"], col: 2, row: 0 },
      { id: "claude", label: "Claude Code", lines: ["`~/.claude/settings.json`"], col: 2, row: 1 },
      { id: "codex", label: "Codex", lines: ["`~/.codex/config.toml`", "`~/.codex/rules/twsrt.rules`"], col: 2, row: 2 },
      { id: "copilot", label: "Copilot CLI", lines: ["`~/.copilot/settings.json`", "flag snippet"], col: 2, row: 3 },
      { id: "jb", label: "Copilot in JetBrains", lines: ["`github-copilot.xml` per IDE"], col: 2, row: 4 },
    ],
    edges: [
      { from: "frag", to: "gen" }, { from: "conf", to: "gen" },
      { from: "gen", to: "srt", route: "vh" }, { from: "gen", to: "claude", route: "vh" },
      { from: "gen", to: "codex" },
      { from: "gen", to: "copilot", route: "vh" }, { from: "gen", to: "jb", route: "vh" },
    ],
  },
  // Question: which stages turn fragments into files, and which files does each command show or write?
  compile: {
    title: "Compile once per profile, then translate per agent",
    cols: 5, rows: 2.45, cellW: 160, cellH: 120, boxW: 140,
    nodes: [
      { id: "frag", label: "Fragments", sub: "JSONC", col: 0, row: 0 },
      { id: "comp", label: "Compose", sub: "profile selects", col: 1, row: 0 },
      { id: "canon", label: "Canonical docs", sub: "source of truth", col: 2, row: 0, kind: "accent" },
      { id: "rules", label: "Normalized rules", sub: "parsed, in memory", col: 3, row: 0 },
      { id: "gens", label: "Generators", sub: "one per agent", col: 4, row: 0 },
      { id: "files", label: "Canonical files", lines: ["`srt-settings.json`", "`bash-rules.json`", "written by any `-w`", "inspect: `twsrt show`"], col: 2, row: 1.25, w: 168 },
      { id: "agents", label: "Agent configs", lines: ["translated, lossy", "written by", "`generate <agent> -w`", "preview: omit `-w`"], col: 3.95, row: 1.25, w: 168 },
      { id: "srt", label: "srt sandbox", sub: "reads its file", col: 0, row: 1.25, kind: "muted" },
    ],
    edges: [
      { from: "frag", to: "comp" }, { from: "comp", to: "canon" }, { from: "canon", to: "rules" },
      { from: "rules", to: "gens" }, { from: "canon", to: "files" }, { from: "gens", to: "agents" },
      { from: "files", to: "srt", dashed: true, label: "read at launch" },
    ],
    legend: [
      { text: "compile and translate" },
      { text: "read at runtime", dashed: true },
    ],
  },
  // Question: which layer guards which kind of access?
  layers: {
    title: "Two enforcement layers: agent permissions for every tool, the kernel sandbox for every spawned command",
    cols: 4, rows: 4.2, cellW: 200, cellH: 104, boxW: 168,
    nodes: [
      { id: "call", label: "Tool call", sub: "from the model", col: 0, row: 1, kind: "muted", w: 140 },
      { id: "perm", label: "Layer 2: permissions", sub: "agent's own engine", lines: ["deny / ask / allow", "every tool call"], col: 1, row: 1, kind: "accent", w: 172 },
      { id: "tools", label: "Built-in tools", lines: ["Read · Edit · WebFetch", "run inside the agent"], col: 2, row: 0.35 },
      { id: "bash", label: "Bash tool", sub: "spawns a process", col: 2, row: 1.9 },
      { id: "cmd", label: "Spawned command", lines: ["deny paths", "write allowlist", "domain allowlist (proxy)"], col: 2, row: 3.1 },
      { id: "res", label: "Files · secrets · network", col: 3, row: 1.7, w: 180 },
    ],
    groups: [
      { label: "agent process", cols: [1, 2], rows: [0, 1.8] },
      { label: "Layer 1: kernel sandbox", cols: [1, 2], rows: [2.85, 3.15] },
    ],
    edges: [
      { from: "call", to: "perm" },
      { from: "perm", to: "tools" },
      { from: "perm", to: "bash" },
      { from: "bash", to: "cmd" },
      { from: "tools", to: "res", kind: "attention", strong: true },
      { from: "cmd", to: "res", kind: "success", strong: true },
    ],
    legend: [
      { text: "agent permissions only", kind: "attention", strong: true },
      { text: "also enforced by the kernel", kind: "success", strong: true },
    ],
  },
  // Question: what does srt confine when an agent runs inside it?
  srt: {
    title: "srt -c 'copilot --yolo': the kernel sandbox confines the whole agent process",
    cols: 4, rows: 3, cellW: 200, cellH: 100, boxW: 166,
    nodes: [
      { id: "launch", label: "srt -c 'copilot --yolo'", lines: ["loads, loss-less:", "`~/.srt-settings.json`"], col: 0, row: 1.2, kind: "accent", w: 180 },
      { id: "agent", label: "copilot --yolo", sub: "agent process", lines: ["own path, URL checks off"], col: 1, row: 1.2 },
      { id: "tools", label: "Built-in tools", lines: ["Read · Edit · WebFetch", "run inside the agent"], col: 2, row: 0.5 },
      { id: "cmds", label: "Spawned commands", lines: ["shell, MCP servers", "and their children"], col: 2, row: 1.9 },
      { id: "res", label: "Files · secrets · network", col: 3, row: 1.2, w: 180 },
    ],
    groups: [
      { label: "srt kernel sandbox: deny paths, write allowlist, domain allowlist", cols: [1, 2], rows: [0, 2.0] },
    ],
    edges: [
      { from: "launch", to: "agent" },
      { from: "agent", to: "tools" },
      { from: "agent", to: "cmds" },
      { from: "tools", to: "res", kind: "success", strong: true },
      { from: "cmds", to: "res", kind: "success", strong: true },
    ],
    legend: [
      { text: "enforced by the kernel sandbox", kind: "success", strong: true },
    ],
  },
  // Question: which command checks which step, and against how many profiles?
  verify: {
    title: "Three read-only checks, one per step from fragments to enforcement",
    cols: 5, rows: 2.3, cellW: 160, cellH: 118, boxW: 140,
    nodes: [
      { id: "frag", label: "Fragments", sub: "+ config.toml", col: 0, row: 0 },
      { id: "files", label: "Files on disk", sub: "canonical + agents", col: 2, row: 0 },
      { id: "srt", label: "srt sandbox", sub: "kernel enforcement", col: 4, row: 0, kind: "muted" },
      { id: "doctor", label: "twsrt doctor", lines: ["valid, no dead weight?", "every profile", "exit 0 ok · 1 errors"], col: 0.05, row: 1.25, kind: "accent", w: 156 },
      { id: "diff", label: "twsrt diff", lines: ["files match fragments?", "one profile (`-p`)", "exit 0 · 1 drift · 2 missing"], col: 1.6, row: 1.25, kind: "accent", w: 176 },
      { id: "test", label: "twsrt test", lines: ["srt enforces the file?", "one profile (`-p`)", "exit 0 · 1 fail · 2 setup"], col: 3.5, row: 1.25, kind: "accent", w: 168 },
    ],
    edges: [
      { from: "frag", to: "files", label: "generate -w" },
      { from: "files", to: "srt", dashed: true, label: "read at launch" },
      { from: "doctor", to: "frag", kind: "accent", dashed: true },
      { from: "diff", to: "frag", kind: "accent", dashed: true },
      { from: "diff", to: "files", kind: "accent", dashed: true },
      { from: "test", to: "files", kind: "accent", dashed: true },
      { from: "test", to: "srt", kind: "accent", dashed: true },
    ],
    legend: [
      { text: "generate" },
      { text: "read at runtime", dashed: true },
      { text: "checks (writes nothing)", kind: "accent", dashed: true },
    ],
  },
};

mkdirSync(OUT, { recursive: true });
for (const [name, spec] of Object.entries(DIAGRAMS)) {
  writeFileSync(join(OUT, `${name}.svg`), boxDiagram(name, spec));
  console.log(`wrote ${join("doc", "diagrams", `${name}.svg`)}`);
}
