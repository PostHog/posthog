// products/mcp/typescript/tests/unit/schema.ajv.test.ts
// Guard test: compiles MCP tool input schemas with AJV in strict mode.
// Kept SKIPPED until upstream schema fixes land.

import { test, expect } from 'vitest'; // use test.skip rather than describe.skip
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import Ajv from 'ajv';
import addFormats from 'ajv-formats';

// NOTE: Using test.skip so the callback body doesn't execute at all while skipped.
// Vitest still registers describe() bodies even when skipped, but test.skip won't run the body. :contentReference[oaicite:0]{index=0}
test.skip('AJV strict compiles all MCP tool input schemas', async () => {
  // Resolve ../../schema/tool-inputs.json relative to this test file
  const __filename = fileURLToPath(import.meta.url);
  const __dirname = path.dirname(__filename);
  const schemaPath = path.resolve(__dirname, '../../schema/tool-inputs.json');

  let doc: unknown;
  try {
    const src = await readFile(schemaPath, 'utf8');
    doc = JSON.parse(src);
  } catch (err) {
    // Helpful guidance if the file is missing
    throw new Error(
      `Could not read schema file at ${schemaPath}.
If this package generates schemas, run: pnpm -C products/mcp schema:build:json`
    );
  }

  // Support multiple shapes:
  // - { [toolName]: schema }
  // - { tools: { [toolName]: schema } }
  // - { tools: Array<{ name, inputSchema }> }
  // - Plain array of { name, inputSchema }
  const extract = (value: any): Array<{ name: string; schema: any }> => {
    if (!value) return [];
    if (Array.isArray(value)) {
      return value
        .map((t) => ('inputSchema' in t ? { name: t.name ?? 'unknown', schema: t.inputSchema } : null))
        .filter(Boolean) as Array<{ name: string; schema: any }>;
    }
    if (value.tools) return extract(value.tools);
    if (typeof value === 'object') {
      return Object.entries(value).map(([name, schema]) => ({ name, schema }));
    }
    return [];
  };

  const items = extract(doc);
  expect(items.length).toBeGreaterThan(0);

  const ajv = new Ajv({ strict: true, allErrors: true }); // strict mode surfaces schema problems early. :contentReference[oaicite:1]{index=1}
  addFormats(ajv);

  const failures: Array<{ name: string; error: unknown }> = [];
  for (const { name, schema } of items) {
    try {
      ajv.compile(schema); // throws on strict violations. :contentReference[oaicite:2]{index=2}
    } catch (err) {
      failures.push({ name, error: err });
    }
  }

  // If/when we un-skip, this assertion will fail fast on any invalid schema.
  expect(failures, JSON.stringify(failures, null, 2)).toHaveLength(0);
});
