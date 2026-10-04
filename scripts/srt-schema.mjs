#!/usr/bin/env node
// Print the key tree of srt's config schema (zod v3) from the installed package.
// srt ships no JSON schema and zod v3 cannot export one, so this walks the zod
// definitions; Node, not Python, because it must import the schema module itself.
// Usage: scripts/srt-schema.mjs [path-to-sandbox-config.js]
// ponytail: reads zod v3 internals (_def.typeName); breaks on a zod v4 upgrade,
// where z.toJSONSchema() replaces this script.
import { execSync } from "node:child_process";
import { realpathSync } from "node:fs";
import { dirname, join } from "node:path";

const defaultPath = () => {
  const bin = execSync("command -v srt", { shell: "/bin/bash" }).toString().trim();
  return join(dirname(realpathSync(bin)), "sandbox", "sandbox-config.js");
};
const { SandboxRuntimeConfigSchema } = await import(process.argv[2] ?? defaultPath());

// Peel wrappers (optional, default, effects, ...) and remember them as flags.
function unwrap(s) {
  const flags = [];
  for (;;) {
    const t = s._def.typeName;
    if (t === "ZodOptional") { flags.push("optional"); s = s._def.innerType; }
    else if (t === "ZodNullable") { flags.push("nullable"); s = s._def.innerType; }
    else if (t === "ZodDefault") { flags.push(`default=${JSON.stringify(s._def.defaultValue())}`); s = s._def.innerType; }
    else if (t === "ZodEffects") { s = s._def.schema; }
    else if (t === "ZodLazy") { s = s._def.getter(); }
    else if (t === "ZodBranded" || t === "ZodReadonly" || t === "ZodCatch") { s = s._def.innerType ?? s._def.type; }
    else return { s, flags };
  }
}

function typeLabel(s) {
  const d = s._def;
  switch (d.typeName) {
    case "ZodString": return "string";
    case "ZodNumber": return "number";
    case "ZodBoolean": return "boolean";
    case "ZodLiteral": return JSON.stringify(d.value);
    case "ZodEnum": return d.values.map((v) => JSON.stringify(v)).join(" | ");
    case "ZodArray": return `${typeLabel(unwrap(d.type).s)}[]`;
    case "ZodRecord": return `record<string, ${typeLabel(unwrap(d.valueType).s)}>`;
    case "ZodUnion": return d.options.map((o) => typeLabel(unwrap(o).s)).join(" | ");
    case "ZodObject": return "object";
    default: return d.typeName.replace(/^Zod/, "").toLowerCase();
  }
}

function walk(schema, indent = "") {
  const { s } = unwrap(schema);
  const shape = s._def.typeName === "ZodObject" ? s.shape
    : s._def.typeName === "ZodArray" && unwrap(s._def.type).s._def.typeName === "ZodObject" ? unwrap(s._def.type).s.shape
    : s._def.typeName === "ZodRecord" && unwrap(s._def.valueType).s._def.typeName === "ZodObject" ? unwrap(s._def.valueType).s.shape
    : null;
  if (shape === null) return;
  for (const [key, child] of Object.entries(shape)) {
    const { s: inner, flags } = unwrap(child);
    const desc = child.description ?? inner.description;
    const meta = [typeLabel(inner), ...flags].join(", ");
    console.log(`${indent}${key}: ${meta}${desc ? `  # ${desc.split("\n")[0]}` : ""}`);
    walk(inner, indent + "  ");
  }
}

walk(SandboxRuntimeConfigSchema);
