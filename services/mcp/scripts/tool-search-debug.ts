#!/usr/bin/env tsx
/**
 * tool-search-debug — reproduce PostHog MCP tool search locally, no MCP server.
 *
 * In single-exec mode the server exposes only `exec`; agents discover the real
 * tools via `exec search <pattern>`. That search compiles the pattern as ONE
 * case-insensitive regex over name/title/description (src/tools/exec.ts:237), so a
 * natural-language query like "create dashboard insight" becomes
 * /create dashboard insight/i and matches nothing — no tool contains that literal
 * phrase. This script runs that exact predicate against the real tool catalog so
 * you can see what `exec search` returns, plus a token-ranked mode for comparison,
 * without booting the MCP. It searches the full unfiltered catalog (no scope or
 * feature-flag gating), so it shows the upper bound of what a query could match.
 *
 * Usage:
 *   npx tsx scripts/tool-search-debug.ts "<query>"
 *   npx tsx scripts/tool-search-debug.ts --mode regex  "dashboard"
 *   npx tsx scripts/tool-search-debug.ts --mode tokens "create dashboard insight"
 *   npx tsx scripts/tool-search-debug.ts --mode both   "create dashboard insight"
 *   npx tsx scripts/tool-search-debug.ts --json --limit 30 "insight"
 *
 * Modes:
 *   regex  (default) — faithful copy of exec's search predicate
 *   tokens           — whitespace-split, ranked by distinct query tokens matched
 *   both             — run both, side by side
 */
import * as fs from 'node:fs'
import * as path from 'node:path'

const MCP_ROOT = path.resolve(__dirname, '..')
const CATALOG_PATH = path.resolve(MCP_ROOT, 'schema', 'tool-definitions-all.json')

/** Mirrors MAX_SEARCH_PATTERN_LENGTH in src/tools/exec.ts. */
const MAX_SEARCH_PATTERN_LENGTH = 200

const FIELD_WEIGHT = { name: 3, title: 2, description: 1 } as const
type Field = keyof typeof FIELD_WEIGHT

type Mode = 'regex' | 'tokens' | 'both'

interface ToolEntry {
    name: string
    title: string
    description: string
}

interface RegexResult {
    pattern: string
    matches: string[]
    error?: string
}

interface ScoredTool {
    name: string
    /** Distinct query tokens found in any field — the primary relevance signal. */
    tokensMatched: number
    /** Field-weighted score, tie-breaker once token coverage is equal. */
    score: number
    fields: Field[]
}

interface Args {
    mode: Mode
    json: boolean
    limit: number
    query: string
}

function loadCatalog(): ToolEntry[] {
    const raw = JSON.parse(fs.readFileSync(CATALOG_PATH, 'utf-8')) as Record<
        string,
        { title?: string; description?: string }
    >
    return Object.entries(raw).map(([name, def]) => ({
        name,
        title: def.title ?? '',
        description: def.description ?? '',
    }))
}

// Faithful copy of the `search` predicate in src/tools/exec.ts:220-262 — same
// length cap, same invalid-regex guard, same case-insensitive test over
// name/title/description. Kept as a copy (not an import) so this debug script
// stays decoupled from the server runtime; the line reference flags drift.
function searchRegex(tools: ToolEntry[], pattern: string): RegexResult {
    if (pattern.length > MAX_SEARCH_PATTERN_LENGTH) {
        return {
            pattern,
            matches: [],
            error: `pattern too long (${pattern.length} chars, max ${MAX_SEARCH_PATTERN_LENGTH})`,
        }
    }
    let regex: RegExp
    try {
        regex = new RegExp(pattern, 'i')
    } catch {
        return { pattern, matches: [], error: `invalid regex pattern: "${pattern}"` }
    }
    const matches = tools
        .filter((t) => regex.test(t.name) || regex.test(t.title) || regex.test(t.description))
        .map((t) => t.name)
    return { pattern, matches }
}

// Candidate ranked search for comparison — not what the server runs today.
// Splits the query into tokens and ranks by how many distinct tokens appear in a
// tool's metadata, so multi-word intents like "create dashboard insight" surface
// dashboard-create / insight-create instead of returning nothing.
function searchTokens(tools: ToolEntry[], query: string): ScoredTool[] {
    const tokens = [...new Set(query.toLowerCase().split(/\s+/).filter(Boolean))]
    if (tokens.length === 0) {
        return []
    }
    const scored: ScoredTool[] = []
    for (const t of tools) {
        const haystack: Record<Field, string> = {
            name: t.name.toLowerCase(),
            title: t.title.toLowerCase(),
            description: t.description.toLowerCase(),
        }
        let tokensMatched = 0
        let score = 0
        const fields = new Set<Field>()
        for (const token of tokens) {
            // Count each token once, at its highest-weight field, so a token in the
            // name outweighs the same token buried in a description.
            const field = (['name', 'title', 'description'] as Field[]).find((f) => haystack[f].includes(token))
            if (field) {
                tokensMatched += 1
                score += FIELD_WEIGHT[field]
                fields.add(field)
            }
        }
        if (tokensMatched > 0) {
            scored.push({ name: t.name, tokensMatched, score, fields: [...fields] })
        }
    }
    // Field-weighted score first: a token in the tool name beats the same token
    // buried in a description, so dashboard-create outranks a tool that merely
    // mentions "create"/"dashboard"/"insight" in prose. Token coverage breaks ties.
    scored.sort((a, b) => b.score - a.score || b.tokensMatched - a.tokensMatched || a.name.localeCompare(b.name))
    return scored
}

function parseArgs(argv: string[]): Args {
    let mode: Mode = 'regex'
    let json = false
    let limit = 20
    const rest: string[] = []
    for (let i = 0; i < argv.length; i++) {
        const arg = argv[i]
        if (arg === '--mode') {
            const next = argv[++i]
            if (next !== undefined) {
                mode = next as Mode
            }
        } else if (arg === '--json') {
            json = true
        } else if (arg === '--limit') {
            const next = argv[++i]
            if (next !== undefined) {
                limit = Number(next)
            }
        } else if (arg === '--help' || arg === '-h') {
            printUsage()
            process.exit(0)
        } else if (arg !== undefined) {
            rest.push(arg)
        }
    }
    return { mode, json, limit, query: rest.join(' ') }
}

function printUsage(): void {
    process.stdout.write(
        [
            'Usage: tsx scripts/tool-search-debug.ts [--mode regex|tokens|both] [--json] [--limit N] "<query>"',
            '',
            '  regex  (default)  faithful reproduction of `exec search` (single case-insensitive regex)',
            '  tokens            candidate ranked search (whitespace-split, ranked by tokens matched)',
            '  both              run both side by side',
            '',
        ].join('\n')
    )
}

function renderRegex(result: RegexResult, limit: number): string {
    const lines = [`▶ regex mode  (exact reproduction of \`exec search\`)`, `  pattern: /${result.pattern}/i`]
    if (result.error) {
        lines.push(`  error: ${result.error}`)
        return lines.join('\n')
    }
    if (result.matches.length === 0) {
        lines.push('  0 matches — the query is tested as one literal regex, so a multi-word phrase rarely matches.')
        return lines.join('\n')
    }
    lines.push(`  ${result.matches.length} match(es)${result.matches.length > limit ? `, showing ${limit}` : ''}:`)
    for (const name of result.matches.slice(0, limit)) {
        lines.push(`    ${name}`)
    }
    return lines.join('\n')
}

function renderTokens(scored: ScoredTool[], query: string, limit: number): string {
    const tokens = [...new Set(query.toLowerCase().split(/\s+/).filter(Boolean))]
    const lines = [`▶ tokens mode  (candidate ranked search)`, `  tokens: ${tokens.join(', ')}`]
    if (scored.length === 0) {
        lines.push('  0 matches.')
        return lines.join('\n')
    }
    lines.push(`  ${scored.length} match(es)${scored.length > limit ? `, showing top ${limit}` : ''}:`)
    lines.push(`    ${'score'.padEnd(6)} ${'cover'.padEnd(5)} ${'matched in'.padEnd(18)} tool`)
    for (const t of scored.slice(0, limit)) {
        const score = String(t.score).padEnd(6)
        const cover = `${t.tokensMatched}/${tokens.length}`.padEnd(5)
        const where = t.fields.join('+').padEnd(18)
        lines.push(`    ${score} ${cover} ${where} ${t.name}`)
    }
    return lines.join('\n')
}

function main(): void {
    const args = parseArgs(process.argv.slice(2))
    if (!args.query) {
        printUsage()
        process.exitCode = 1
        return
    }
    if (args.mode !== 'regex' && args.mode !== 'tokens' && args.mode !== 'both') {
        process.stderr.write(`Unknown mode: "${args.mode}". Use regex, tokens, or both.\n`)
        process.exitCode = 1
        return
    }

    const tools = loadCatalog()
    const regex = args.mode !== 'tokens' ? searchRegex(tools, args.query) : undefined
    const tokens = args.mode !== 'regex' ? searchTokens(tools, args.query) : undefined

    if (args.json) {
        process.stdout.write(
            JSON.stringify(
                {
                    query: args.query,
                    catalog: { path: path.relative(MCP_ROOT, CATALOG_PATH), tools: tools.length },
                    ...(regex ? { regex } : {}),
                    ...(tokens ? { tokens: tokens.slice(0, args.limit) } : {}),
                },
                null,
                2
            ) + '\n'
        )
        return
    }

    const blocks = [
        `Catalog: ${tools.length} tools (${path.relative(MCP_ROOT, CATALOG_PATH)})`,
        `Query:   "${args.query}"`,
        '',
    ]
    if (regex) {
        blocks.push(renderRegex(regex, args.limit), '')
    }
    if (tokens) {
        blocks.push(renderTokens(tokens, args.query, args.limit), '')
    }
    process.stdout.write(blocks.join('\n'))
}

main()
