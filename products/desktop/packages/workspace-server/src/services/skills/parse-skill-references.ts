const SLASH_REFERENCE_REGEX =
  /(?<=^|[\s(`"'[])\/([A-Za-z0-9][A-Za-z0-9._-]*)(?![A-Za-z0-9._/-])/gm;
const WIKI_LINK_REGEX = /\[\[([A-Za-z0-9][A-Za-z0-9._-]*)\]\]/g;

/**
 * Finds `/skill-name` and `[[skill-name]]` references in a SKILL.md body.
 * Only names in `knownNames` are returned, so paths (`/usr/bin`), URL
 * segments, and unrelated slash-words can't match. A slash reference must
 * span its whole path segment — `/foo/bar` never matches a skill named `foo`.
 */
export function parseSkillReferences(
  content: string,
  knownNames: ReadonlySet<string>,
): string[] {
  const references = new Set<string>();

  for (const regex of [SLASH_REFERENCE_REGEX, WIKI_LINK_REGEX]) {
    for (const match of content.matchAll(regex)) {
      const name = match[1];
      if (knownNames.has(name)) {
        references.add(name);
        continue;
      }
      // dots are valid name chars, so a sentence-final "/dep-skill." captures the period
      const withoutTrailingDots = name.replace(/\.+$/, "");
      if (withoutTrailingDots !== name && knownNames.has(withoutTrailingDots)) {
        references.add(withoutTrailingDots);
      }
    }
  }

  return [...references];
}
