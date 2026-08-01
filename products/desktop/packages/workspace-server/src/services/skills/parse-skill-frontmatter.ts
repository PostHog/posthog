/**
 * Parses YAML frontmatter from a SKILL.md file.
 * Extracts `name` and `description` fields.
 *
 * Handles:
 * - Simple values: `name: my-skill`
 * - Quoted strings: `description: 'Some text'` or `description: "Some text"`
 * - Multi-line folded: `description: >-\n  line1\n  line2`
 */
export function parseSkillFrontmatter(
  content: string,
): { name: string; description: string } | null {
  const match = content.match(/^---\r?\n([\s\S]*?)\r?\n---/);
  if (!match) return null;

  const yaml = match[1];
  const name = extractYamlValue(yaml, "name");
  if (!name) return null;

  const description = extractYamlValue(yaml, "description") ?? "";
  return { name, description };
}

/**
 * Extracts the optional `dependencies` list from a SKILL.md frontmatter — the
 * names of other skills this skill needs. Supports flow (`dependencies: [a, b]`)
 * and block (`dependencies:\n  - a\n  - b`) sequences. Returns [] when absent.
 */
export function parseSkillDependencies(content: string): string[] {
  const match = content.match(/^---\r?\n([\s\S]*?)\r?\n---/);
  if (!match) return [];
  return extractYamlList(match[1], "dependencies");
}

function unquoteYamlScalar(value: string): string {
  if (
    (value.startsWith("'") && value.endsWith("'")) ||
    (value.startsWith('"') && value.endsWith('"'))
  ) {
    return value.slice(1, -1);
  }
  return value;
}

function extractYamlList(yaml: string, key: string): string[] {
  const lines = yaml.split("\n");
  // Match `key:` at the start of the line with a literal prefix rather than a
  // RegExp built from the (caller-supplied) key — avoids a metacharacter
  // footgun if this helper is ever reused with a key like `my.key`.
  const prefix = `${key}:`;

  for (let i = 0; i < lines.length; i++) {
    if (!lines[i].startsWith(prefix)) continue;

    const inline = lines[i].slice(prefix.length).trim();
    // Flow sequence or comma list: `[a, b]` / `a, b`
    if (inline) {
      const stripped = inline.replace(/^\[/, "").replace(/\]$/, "");
      return stripped
        .split(",")
        .map((entry) => unquoteYamlScalar(entry.trim()))
        .filter((entry) => entry.length > 0);
    }

    // Block sequence: subsequent `- item` lines
    const items: string[] = [];
    for (let j = i + 1; j < lines.length; j++) {
      const itemMatch = lines[j].match(/^\s*-\s+(.*)$/);
      if (!itemMatch) {
        if (/^\s*$/.test(lines[j])) continue;
        break;
      }
      const value = unquoteYamlScalar(itemMatch[1].trim());
      if (value) items.push(value);
    }
    return items;
  }

  return [];
}

function extractYamlValue(yaml: string, key: string): string | null {
  const lines = yaml.split("\n");

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const keyPattern = new RegExp(`^${key}:\\s*(.*)$`);
    const match = line.match(keyPattern);
    if (!match) continue;

    const rawValue = match[1].trim();

    // Multi-line folded scalar (>- or >)
    if (rawValue === ">-" || rawValue === ">") {
      return collectIndentedLines(lines, i + 1).join(" ");
    }

    // Multi-line literal scalar (|- or |)
    if (rawValue === "|-" || rawValue === "|") {
      return collectIndentedLines(lines, i + 1).join("\n");
    }

    // Quoted string (single or double)
    if (
      (rawValue.startsWith("'") && rawValue.endsWith("'")) ||
      (rawValue.startsWith('"') && rawValue.endsWith('"'))
    ) {
      return rawValue.slice(1, -1);
    }

    // Plain scalar
    return rawValue;
  }

  return null;
}

function collectIndentedLines(lines: string[], startIndex: number): string[] {
  const result: string[] = [];
  let pendingBlanks = 0;
  for (let i = startIndex; i < lines.length; i++) {
    const line = lines[i];
    // Blank lines only count if more indented content follows.
    if (/^\s*$/.test(line)) {
      pendingBlanks++;
      continue;
    }
    // Continuation lines must be indented
    if (line.match(/^\s+\S/)) {
      if (result.length > 0) {
        for (let b = 0; b < pendingBlanks; b++) result.push("");
      }
      pendingBlanks = 0;
      result.push(line.trim());
    } else {
      break;
    }
  }
  return result;
}
