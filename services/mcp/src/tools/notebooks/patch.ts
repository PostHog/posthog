/**
 * Patch format and parser.
 *
 * Mirrors OpenAI's `apply_patch` text shape, simplified for a single-document
 * target (a notebook has no concept of multiple files). One patch contains one
 * or more hunks; each hunk is a sequence of context (` `), removed (`-`) and
 * added (`+`) lines.
 *
 *   *** Begin Patch
 *   @@
 *    # My notebook
 *   -Old paragraph text
 *   +New paragraph text
 *   +Another new paragraph
 *   @@
 *    > A quote
 *   -To delete
 *   *** End Patch
 *
 * Rules:
 *   - `*** Begin Patch` / `*** End Patch` markers are optional. We tolerate
 *     them so agents can copy/paste the apply_patch shape verbatim.
 *   - Each hunk starts with `@@`. Any text after `@@` on the same line is
 *     treated as a hint (ignored by the locator — we use the body lines).
 *   - Each hunk body line starts with one of: ` ` (space, context),
 *     `-` (remove), `+` (add).
 *   - Empty lines inside a hunk must still carry a leading prefix (` `, `-`,
 *     `+`). A bare empty line ends the hunk.
 *   - Hunks are applied in order; later hunks operate on text that earlier
 *     hunks have already produced.
 *
 * The patch operates on lines, but each line corresponds to one top-level
 * block in the notebook document (see textRender.ts). That's why blocks are
 * the unit of edit — the agent can add, remove, or replace whole blocks but
 * cannot perform sub-block character edits without rewriting the whole block.
 */

export type HunkLineKind = 'context' | 'add' | 'remove'

export interface HunkLine {
    kind: HunkLineKind
    /** Line text without the leading marker (` `, `-`, `+`). */
    text: string
}

export interface Hunk {
    lines: HunkLine[]
}

export interface ParsedPatch {
    hunks: Hunk[]
}

const BEGIN_MARKER = '*** Begin Patch'
const END_MARKER = '*** End Patch'

export class PatchParseError extends Error {
    public readonly lineNumber: number
    constructor(message: string, lineNumber: number) {
        super(`Patch parse error on line ${lineNumber}: ${message}`)
        this.name = 'PatchParseError'
        this.lineNumber = lineNumber
    }
}

export function parsePatch(patch: string): ParsedPatch {
    const rawLines = patch.replace(/\r\n/g, '\n').split('\n')
    const hunks: Hunk[] = []
    let current: Hunk | null = null
    let started = false

    const flush = (): void => {
        if (current && current.lines.length > 0) {
            hunks.push(current)
        }
        current = null
    }

    for (let i = 0; i < rawLines.length; i++) {
        const line = rawLines[i]!
        const lineNumber = i + 1

        if (line === BEGIN_MARKER) {
            started = true
            continue
        }
        if (line === END_MARKER) {
            break
        }

        if (line.startsWith('@@')) {
            flush()
            current = { lines: [] }
            started = true
            continue
        }

        if (current === null) {
            // Tolerate blank lines and surrounding prose before the first `@@`,
            // as agents commonly wrap the patch in markdown fences or
            // explanatory text.
            if (line.trim() === '') {
                continue
            }
            if (started) {
                // Once we've seen a marker or `@@`, anything outside a hunk is
                // an error so we don't silently swallow malformed patches.
                throw new PatchParseError(`Unexpected content outside hunk: ${JSON.stringify(line)}`, lineNumber)
            }
            continue
        }

        if (line === '') {
            // Bare empty line terminates the hunk; the next `@@` or marker
            // starts a new one. This matches apply_patch behaviour and lets
            // patches sit inside markdown blocks without trailing whitespace
            // pulling in unintended content.
            flush()
            continue
        }

        const marker = line[0]
        const rest = line.slice(1)
        if (marker === ' ') {
            current.lines.push({ kind: 'context', text: rest })
        } else if (marker === '-') {
            current.lines.push({ kind: 'remove', text: rest })
        } else if (marker === '+') {
            current.lines.push({ kind: 'add', text: rest })
        } else {
            throw new PatchParseError(
                `Each hunk line must start with ' ', '-' or '+'. Got: ${JSON.stringify(line)}`,
                lineNumber
            )
        }
    }
    flush()

    if (hunks.length === 0) {
        throw new PatchParseError('No hunks found in patch. Expected at least one `@@` block.', 0)
    }
    return { hunks }
}

/**
 * Project a hunk down to two sequences of lines: the "before" state (context
 * + removed) and the "after" state (context + added). Used by the locator to
 * find the hunk in the doc and by the step builder to compute the replacement.
 */
export function hunkBefore(hunk: Hunk): string[] {
    return hunk.lines.filter((l) => l.kind !== 'add').map((l) => l.text)
}

export function hunkAfter(hunk: Hunk): string[] {
    return hunk.lines.filter((l) => l.kind !== 'remove').map((l) => l.text)
}
