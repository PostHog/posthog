#!/usr/bin/env tsx
/**
 * Scaffolds and maintains YAML tool definitions from the OpenAPI schema.
 *
 * Discovers operations by the x-product values the spec emits per operation:
 * auto-derived from the ViewSet module path (products/<name>/backend/) or
 * declared explicitly via @extend_schema(extensions={"x-product": "<name>"}).
 * There is deliberately no URL-based guessing — paths are a lossy projection
 * of ownership and used to poach operations across products.
 *
 * Tools are opt-in. An operation has a YAML entry only when someone added it
 * (`--add`) or keeps it off on purpose (`enabled: false` + `disabled_reason`).
 * Sync never writes entries for new operations, so a new endpoint does not
 * rewrite the product's YAML file. `--candidates` lists the operations that
 * have no entry yet.
 *
 * Usage:
 *   pnpm scaffold-yaml --product error_tracking --output ../../products/error_tracking/mcp/tools.yaml
 *   pnpm scaffold-yaml --candidates --product error_tracking
 *   pnpm scaffold-yaml --add error_tracking_issues_list --product error_tracking [--file <yaml>]
 *   pnpm scaffold-yaml --sync-all
 */
import { spawnSync } from 'node:child_process'
import * as fs from 'node:fs'
import * as path from 'node:path'
import { fileURLToPath } from 'node:url'
import { parse as parseYaml, stringify as stringifyYaml } from 'yaml'

import { discoverDefinitions } from './lib/definitions.mjs'
import { type CategoryConfig, CategoryConfigSchema } from './yaml-config-schema'

const MCP_ROOT = path.resolve(__dirname, '..')
const REPO_ROOT = path.resolve(MCP_ROOT, '../..')
const PRODUCTS_DIR = path.resolve(REPO_ROOT, 'products')
const OPENAPI_PATH = path.resolve(REPO_ROOT, 'frontend/tmp/openapi.json')
const DEFINITIONS_DIR = path.resolve(MCP_ROOT, 'definitions')

const productAliases: Record<string, string> = {
    llm_analytics: 'ai_observability',
}

// ------------------------------------------------------------------
// Types
// ------------------------------------------------------------------

interface OpenApiOperation {
    operationId: string
    parameters?: Array<{ in: string; name: string }>
    summary?: string
    description?: string
    deprecated?: boolean
    'x-product'?: string[]
}

interface OpenApiSpec {
    paths: Record<string, Record<string, OpenApiOperation>>
}

interface DiscoveredOperation {
    operationId: string
    method: string
    path: string
    summary?: string | undefined
    description?: string | undefined
}

function yamlHeader(product: string): string {
    return `# MCP tool definitions. Tools are opt-in: an operation is exposed only when it has an entry here.
# List operations without an entry: pnpm --filter=@posthog/mcp run scaffold-yaml -- --candidates --product ${product}
# Add one: pnpm --filter=@posthog/mcp run scaffold-yaml -- --add <operationId> --product ${product}
# To keep an operation off on purpose, set enabled: false and give a disabled_reason.
`
}

// ------------------------------------------------------------------
// Helpers
// ------------------------------------------------------------------

function formatWithPrettier(filePaths: string[]): void {
    if (filePaths.length === 0) {
        return
    }
    try {
        spawnSync('pnpm', ['exec', 'oxfmt', '--no-error-on-unmatched-pattern', ...filePaths], {
            stdio: 'pipe',
            cwd: REPO_ROOT,
        })
    } catch {
        // Not critical — oxfmt may not be available in all environments
    }
}

function loadOpenApi(): OpenApiSpec {
    if (!fs.existsSync(OPENAPI_PATH)) {
        console.error(`OpenAPI schema not found at ${OPENAPI_PATH}. Run \`hogli build:openapi-schema\` first.`)
        process.exit(1)
    }
    return JSON.parse(fs.readFileSync(OPENAPI_PATH, 'utf-8')) as OpenApiSpec
}

function operationIdToToolName(operationId: string): string {
    return operationId.replace(/[_.]+/g, '-')
}

/** drf-spectacular appends _N to an operationId mounted at several paths (/api/environments/ and /api/projects/). */
function baseOperationId(operationId: string): string {
    return operationId.replace(/_\d+$/, '')
}

/**
 * Find operations whose x-product list names this product. Values are
 * auto-derived from the ViewSet module path (products/<name>/backend/ →
 * "<name>") or declared via @extend_schema(extensions={"x-product": "..."}).
 * Both sides are normalized (kebab → snake) so hyphenated definition
 * filenames like proxy-records match the snake_case x-product value.
 */
function findOperationsByProduct(spec: OpenApiSpec, product: string): DiscoveredOperation[] {
    const ops: DiscoveredOperation[] = []
    const httpMethods = new Set(['get', 'post', 'put', 'patch', 'delete'])
    const normalize = (name: string): string => name.toLowerCase().replace(/-/g, '_')
    const matchingProducts = new Set(
        [
            product,
            ...Object.entries(productAliases)
                .filter(([, target]) => target === product)
                .map(([source]) => source),
        ].map(normalize)
    )

    for (const [urlPath, methods] of Object.entries(spec.paths)) {
        for (const [method, op] of Object.entries(methods)) {
            if (!httpMethods.has(method) || !op?.operationId || op.deprecated) {
                continue
            }
            const xProduct = op['x-product'] ?? []
            if (xProduct.some((value) => matchingProducts.has(normalize(value)))) {
                ops.push({
                    operationId: op.operationId,
                    method: method.toUpperCase(),
                    path: urlPath,
                    summary: op.summary,
                    description: op.description,
                })
            }
        }
    }

    return ops
}

function specHasOperation(spec: OpenApiSpec, operationId: string): boolean {
    return Object.values(spec.paths).some((methods) =>
        Object.values(methods).some((op) => op?.operationId === operationId)
    )
}

/**
 * Deduplicate operations mounted at both /api/environments/ and /api/projects/.
 * Prefers /api/projects/ paths. Uses the clean base operationId (strips _N suffix).
 */
function deduplicateOperations(ops: DiscoveredOperation[]): DiscoveredOperation[] {
    const groups = new Map<string, DiscoveredOperation[]>()
    for (const op of ops) {
        const base = baseOperationId(op.operationId)
        const group = groups.get(base) ?? []
        group.push(op)
        groups.set(base, group)
    }

    const result: DiscoveredOperation[] = []
    for (const [base, group] of groups) {
        if (group.length === 1) {
            result.push(group[0]!)
            continue
        }
        // Prefer /api/projects/ over /api/environments/
        const preferred = group.find((op) => op.path.startsWith('/api/projects/')) ?? group[0]!
        // Use clean base operationId for the tool name
        result.push({ ...preferred, operationId: base })
    }

    return result
}

function renderCategoryYaml(existing: CategoryConfig, tag: string, tools: Record<string, unknown>): string {
    const sortedTools = Object.fromEntries(Object.entries(tools).sort(([a], [b]) => a.localeCompare(b)))

    const merged: Record<string, unknown> = {
        category: existing.category ?? tag.charAt(0).toUpperCase() + tag.slice(1),
        feature: existing.feature ?? tag.replace(/-/g, '_'),
        url_prefix: existing.url_prefix ?? `/${tag.replace(/_/g, '-')}`,
        // Hand-authored category-level gate — sync must not drop it.
        ...(existing.feature_flag ? { feature_flag: existing.feature_flag } : {}),
        ...(existing.feature_flag_behavior ? { feature_flag_behavior: existing.feature_flag_behavior } : {}),
        ...(existing.feature_flag_variant ? { feature_flag_variant: existing.feature_flag_variant } : {}),
        ui_apps: existing.ui_apps ?? {},
        tools: sortedTools,
    }

    // Query wrappers are hand-authored (schema.json); OpenAPI sync must not drop them.
    if (existing.wrappers !== undefined) {
        merged.wrappers = existing.wrappers
    }

    return yamlHeader(tag) + stringifyYaml(merged, { indent: 4, lineWidth: 120 })
}

function generateFreshYaml(tag: string): string {
    const fresh = CategoryConfigSchema.parse({
        category: tag.charAt(0).toUpperCase() + tag.slice(1),
        feature: tag.replace(/-/g, '_'),
        url_prefix: `/${tag.replace(/_/g, '-')}`,
        tools: {},
    })
    return renderCategoryYaml(fresh, tag, {})
}

function loadCategoryConfig(filePath: string): CategoryConfig {
    const parsed = parseYaml(fs.readFileSync(filePath, 'utf-8'))
    const result = CategoryConfigSchema.safeParse(parsed)
    if (!result.success) {
        console.error(`Invalid existing YAML config in ${filePath}:`)
        for (const issue of result.error.issues) {
            console.error(`  ${issue.path.join('.')}: ${issue.message}`)
        }
        process.exit(1)
    }
    return result.data
}

/**
 * Never adds entries for new operations, because tools are opt-in (see `--add`).
 * A disabled entry without a `disabled_reason` is a leftover stub: dropped and
 * reported in `droppedDisabledTools`. An entry whose operation is gone:
 * - enabled: kept and reported in `lostEnabledTools`, because dropping it would
 *   silently remove a live tool.
 * - disabled (with its disabled_reason): dropped and reported in
 *   `droppedDisabledTools`, because the decision no longer applies.
 * - in a subset file: kept and reported in `unmatchedTools`, because a subset
 *   file can reference operations of another product.
 */
function mergeWithExisting(
    existing: CategoryConfig,
    ops: DiscoveredOperation[],
    tag: string,
    validOperationIds: Set<string>,
    subset = false
): {
    content: string
    updated: number
    matched: number
    unmatchedTools: string[]
    lostEnabledTools: string[]
    droppedDisabledTools: string[]
} {
    const openApiByBase = new Map(ops.map((op) => [baseOperationId(op.operationId), op]))
    const mergedTools: Record<string, unknown> = {}
    let updated = 0
    let matched = 0
    const unmatchedTools: string[] = []
    const lostEnabledTools: string[] = []
    const droppedDisabledTools: string[] = []

    for (const [name, config] of Object.entries(existing.tools)) {
        if (!config.enabled && !config.disabled_reason) {
            droppedDisabledTools.push(`${name} (${config.operation}): no disabled_reason`)
            continue
        }
        const op = openApiByBase.get(baseOperationId(config.operation))
        if (op) {
            // Keep the author's chosen operation variant if it still exists in
            // OpenAPI — they may have picked a specific _N suffix deliberately
            // (e.g. _2 for /api/projects/ path). Fall back to the deduped
            // operationId when their variant was renumbered or removed.
            const operation = validOperationIds.has(config.operation) ? config.operation : op.operationId
            mergedTools[name] = { ...config, operation }
            if (operation !== config.operation) {
                updated++
            }
            matched++
        } else if (subset) {
            mergedTools[name] = { ...config }
            unmatchedTools.push(`${name} (${config.operation})`)
        } else if (config.enabled) {
            mergedTools[name] = { ...config }
            lostEnabledTools.push(`${name} (${config.operation})`)
        } else {
            droppedDisabledTools.push(`${name} (${config.operation}): operation no longer in OpenAPI`)
        }
    }

    return {
        content: renderCategoryYaml(existing, tag, mergedTools),
        updated,
        matched,
        unmatchedTools,
        lostEnabledTools,
        droppedDisabledTools,
    }
}

/**
 * An enabled tool whose operation vanished stays in the YAML. Report it and
 * fail the command so the author fixes it before codegen rejects the file.
 */
function reportLostEnabledTools(lostEnabledTools: string[]): void {
    if (lostEnabledTools.length === 0) {
        return
    }
    process.stderr.write(
        `  ✗ ${lostEnabledTools.length} enabled tool(s) reference an operationId that no longer exists in OpenAPI. ` +
            `Fix "operation:" or remove the tool:\n`
    )
    for (const tool of lostEnabledTools) {
        process.stderr.write(`    - ${tool}\n`)
    }
    process.exitCode = 1
}

function reportDroppedDisabledTools(droppedDisabledTools: string[]): void {
    if (droppedDisabledTools.length === 0) {
        return
    }
    process.stdout.write(`  ${droppedDisabledTools.length} disabled tool(s) removed:\n`)
    for (const tool of droppedDisabledTools) {
        process.stdout.write(`    - ${tool}\n`)
    }
}

// Reads every definition file because an operation can be claimed outside its
// product's tools.yaml, for example by a subset file of another product.
function collectClaimedBaseIds(): Set<string> {
    const claimed = new Set<string>()
    for (const { filePath } of discoverDefinitions({ definitionsDir: DEFINITIONS_DIR, productsDir: PRODUCTS_DIR })) {
        const parsed = parseYaml(fs.readFileSync(filePath, 'utf-8')) as { tools?: Record<string, unknown> } | null
        for (const config of Object.values(parsed?.tools ?? {})) {
            const operation = (config as { operation?: unknown } | null)?.operation
            if (typeof operation === 'string') {
                claimed.add(baseOperationId(operation))
            }
        }
    }
    return claimed
}

function findCandidates(spec: OpenApiSpec, product: string, claimedBaseIds: Set<string>): DiscoveredOperation[] {
    return deduplicateOperations(findOperationsByProduct(spec, product))
        .filter((op) => !claimedBaseIds.has(baseOperationId(op.operationId)))
        .sort((a, b) => a.operationId.localeCompare(b.operationId))
}

function oneLine(text: string | undefined, maxLength: number): string {
    const flat = (text ?? '').replace(/\s+/g, ' ').trim()
    return flat.length > maxLength ? `${flat.slice(0, maxLength - 1)}…` : flat
}

function formatCandidates(candidates: DiscoveredOperation[], product: string): string {
    if (candidates.length === 0) {
        return `Every OpenAPI operation of "${product}" already has a YAML entry.\n`
    }
    const idWidth = Math.max(...candidates.map((op) => op.operationId.length))
    const lines = candidates.map((op) =>
        [op.operationId.padEnd(idWidth), op.method.padEnd(6), op.path, oneLine(op.summary || op.description, 80)]
            .join('  ')
            .trimEnd()
    )
    return (
        `${candidates.length} operation(s) of "${product}" have no YAML entry:\n` +
        lines.map((line) => `  ${line}\n`).join('') +
        `\nAdd one as an enabled tool:\n` +
        `  pnpm --filter=@posthog/mcp run scaffold-yaml -- --add <operationId> --product ${product}\n`
    )
}

function buildAddedTool(
    spec: OpenApiSpec,
    product: string,
    operationId: string,
    claimedBaseIds: Set<string>,
    existing: CategoryConfig
): { toolName: string; op: DiscoveredOperation; entry: Record<string, unknown> } {
    const rawOps = findOperationsByProduct(spec, product)
    const ops = deduplicateOperations(rawOps)
    const isProductOperation = [...rawOps, ...ops].some((candidate) => candidate.operationId === operationId)
    if (!isProductOperation) {
        if (specHasOperation(spec, operationId)) {
            throw new Error(
                `Operation "${operationId}" is not attributed to product "${product}". ` +
                    `Pass the product its x-product names, or fix the x-product attribution on the ViewSet.`
            )
        }
        throw new Error(`Operation "${operationId}" is not in the OpenAPI schema. Run hogli build:openapi first.`)
    }

    const base = baseOperationId(operationId)
    if (claimedBaseIds.has(base)) {
        throw new Error(`Operation "${operationId}" already has a YAML entry. Edit that entry instead.`)
    }

    const op = ops.find((candidate) => baseOperationId(candidate.operationId) === base)!
    const toolName = operationIdToToolName(op.operationId)
    if (Object.prototype.hasOwnProperty.call(existing.tools, toolName)) {
        throw new Error(`Tool name "${toolName}" is already used by "${existing.tools[toolName]!.operation}".`)
    }

    // Title and description fall back to the spec in codegen, so the entry only overrides them when needed.
    const entry: Record<string, unknown> = { operation: operationId, enabled: true }
    return { toolName, op, entry }
}

function defaultProductFile(product: string): string | undefined {
    const candidates = [
        path.join(PRODUCTS_DIR, product, 'mcp', 'tools.yaml'),
        path.join(PRODUCTS_DIR, product, 'mcp', 'tools.yml'),
        path.join(DEFINITIONS_DIR, `${product}.yaml`),
        path.join(DEFINITIONS_DIR, `${product}.yml`),
    ]
    return candidates.find((candidate) => fs.existsSync(candidate))
}

// ------------------------------------------------------------------
// CLI
// ------------------------------------------------------------------

/**
 * Re-sync all existing YAML definitions. Derives the product name from the
 * file/directory structure, finds its OpenAPI operations by x-product, and
 * merges them with `mergeWithExisting`. Idempotent, and never adds entries.
 * Runs oxfmt on written files so output matches what lint-staged produces.
 */
function syncAll(spec: OpenApiSpec): void {
    interface SyncTarget {
        product: string
        filePath: string
        /** Subset files (filename != tools.yaml) keep entries whose operation is not found */
        subset: boolean
    }

    const targets: SyncTarget[] = []

    // Core definitions — product derived from filename (e.g. actions.yaml → "actions")
    if (fs.existsSync(DEFINITIONS_DIR)) {
        for (const file of fs.readdirSync(DEFINITIONS_DIR)) {
            if (!file.endsWith('.yaml') && !file.endsWith('.yml')) {
                continue
            }
            // Skip query wrapper configs — they don't map to OpenAPI operations
            const filePath = path.join(DEFINITIONS_DIR, file)
            const parsed = parseYaml(fs.readFileSync(filePath, 'utf-8'))
            if (typeof parsed === 'object' && parsed !== null && 'wrappers' in parsed && !('tools' in parsed)) {
                continue
            }
            targets.push({
                product: file.replace(/\.ya?ml$/, ''),
                filePath,
                subset: false,
            })
        }
    }

    // Product definitions — product always from directory name.
    // Non-tools.yaml files are subset files that own a curated slice of the
    // product's operations (e.g. prompts.yaml inside llm_analytics/mcp/).
    if (fs.existsSync(PRODUCTS_DIR)) {
        for (const entry of fs.readdirSync(PRODUCTS_DIR, { withFileTypes: true })) {
            if (!entry.isDirectory() || entry.name.startsWith('_')) {
                continue
            }
            const mcpDir = path.join(PRODUCTS_DIR, entry.name, 'mcp')
            if (!fs.existsSync(mcpDir)) {
                continue
            }
            for (const file of fs.readdirSync(mcpDir)) {
                if (!file.endsWith('.yaml') && !file.endsWith('.yml')) {
                    continue
                }
                const subset = file !== 'tools.yaml' && file !== 'tools.yml'
                targets.push({ product: entry.name, filePath: path.join(mcpDir, file), subset })
            }
        }
    }

    if (targets.length === 0) {
        process.stdout.write('No existing YAML definitions found.\n')
        return
    }

    const writtenFiles: string[] = []
    const noOpsProducts: string[] = []

    for (const { product, filePath, subset } of targets) {
        const rawOps = findOperationsByProduct(spec, product)
        const ops = deduplicateOperations(rawOps)
        if (ops.length === 0) {
            const label = path.relative(REPO_ROOT, filePath)
            const normalized = product.replace(/-/g, '_').toLowerCase()
            process.stderr.write(
                `⚠ ${label}: no operations found in OpenAPI for "${product}"\n` +
                    `  → declare @extend_schema(extensions={"x-product": "${normalized}"}) on the ViewSet, ` +
                    `or place it in products/${normalized}/backend/ for module-path auto-attribution\n`
            )
            noOpsProducts.push(label)
            continue
        }
        const label = path.relative(REPO_ROOT, filePath)
        const validIds = new Set(rawOps.map((op) => op.operationId))
        const { content, updated, matched, unmatchedTools, lostEnabledTools, droppedDisabledTools } = mergeWithExisting(
            loadCategoryConfig(filePath),
            ops,
            product,
            validIds,
            subset
        )
        fs.writeFileSync(filePath, content)
        writtenFiles.push(filePath)
        const total = matched + unmatchedTools.length
        const parts = [
            subset ? (total === 0 ? '0 tool(s)' : `${matched}/${total} tool(s) matched`) : `${matched} tool(s)`,
        ]
        if (droppedDisabledTools.length > 0) {
            parts.push(`${droppedDisabledTools.length} removed`)
        }
        if (updated > 0) {
            parts.push(`${updated} operation ID(s) updated`)
        }
        if (droppedDisabledTools.length === 0 && updated === 0 && unmatchedTools.length === 0) {
            parts.push('no changes')
        }
        process.stdout.write(`${label}: ${parts.join(', ')}\n`)
        if (unmatchedTools.length > 0) {
            process.stderr.write(
                `  ⚠ ${unmatchedTools.length} tool(s) not found in OpenAPI — add @extend_schema(extensions={"x-product": "${product}"}) to the ViewSet\n`
            )
            for (const tool of unmatchedTools) {
                process.stderr.write(`    - ${tool}\n`)
            }
        }
        reportDroppedDisabledTools(droppedDisabledTools)
        reportLostEnabledTools(lostEnabledTools)
    }

    formatWithPrettier(writtenFiles)

    if (noOpsProducts.length > 0) {
        process.stderr.write(
            `\n${noOpsProducts.length} file(s) had no matching OpenAPI operations — see warnings above\n`
        )
        process.exitCode = 1
    }
}

function addTool(spec: OpenApiSpec, product: string, operationId: string, filePath: string | undefined): void {
    const targetFile = filePath ? path.resolve(MCP_ROOT, filePath) : defaultProductFile(product)
    if (!targetFile || !fs.existsSync(targetFile)) {
        console.error(
            `No YAML file for product "${product}". Create one with ` +
                `--product ${product} --output ../../products/${product}/mcp/tools.yaml, or pass --file <path>.`
        )
        process.exit(1)
    }

    const existing = loadCategoryConfig(targetFile)
    let added: ReturnType<typeof buildAddedTool>
    try {
        added = buildAddedTool(spec, product, operationId, collectClaimedBaseIds(), existing)
    } catch (error) {
        console.error(error instanceof Error ? error.message : String(error))
        process.exit(1)
    }

    fs.writeFileSync(
        targetFile,
        renderCategoryYaml(existing, product, { ...existing.tools, [added.toolName]: added.entry })
    )
    formatWithPrettier([targetFile])

    const label = path.relative(REPO_ROOT, targetFile)
    process.stdout.write(`Added "${added.toolName}" (${added.op.method} ${added.op.path}) to ${label}.\n`)
    process.stdout.write(
        'Next: check the title and description the API gives the tool, set them in the YAML if they do not read well for an agent'
    )
    if (!['GET', 'DELETE'].includes(added.op.method)) {
        process.stdout.write(`, add annotations (required for ${added.op.method})`)
    }
    process.stdout.write(', then run hogli build:openapi to generate the tool.\n')
}

const USAGE = `Usage: scaffold-yaml --product <name> [--output <file>]   create or re-sync one product file
       scaffold-yaml --candidates --product <name>          list operations without a YAML entry
       scaffold-yaml --add <operationId> --product <name> [--file <yaml>]
       scaffold-yaml --sync-all                             re-sync every YAML file

--product discovers endpoints by x-product: module-path auto-attribution,
or declared explicitly via @extend_schema(extensions={"x-product": "..."}).
Uses the product folder name (underscores), e.g. error_tracking, workflows.
--output and --file resolve relative to services/mcp/.`

function main(): void {
    const args = process.argv.slice(2)
    let product: string | undefined
    let outputPath: string | undefined
    let addOperationId: string | undefined
    let filePath: string | undefined

    for (let i = 0; i < args.length; i++) {
        if (args[i] === '--product' && args[i + 1]) {
            product = args[++i]
        } else if (args[i] === '--output' && args[i + 1]) {
            outputPath = args[++i]
        } else if (args[i] === '--add' && args[i + 1]) {
            addOperationId = args[++i]
        } else if (args[i] === '--file' && args[i + 1]) {
            filePath = args[++i]
        }
    }

    if (args.includes('--sync-all')) {
        syncAll(loadOpenApi())
        return
    }

    if (!product) {
        console.error(USAGE)
        process.exit(1)
    }

    if (args.includes('--candidates')) {
        const candidates = findCandidates(loadOpenApi(), product, collectClaimedBaseIds())
        process.stdout.write(formatCandidates(candidates, product))
        return
    }

    if (addOperationId) {
        addTool(loadOpenApi(), product, addOperationId, filePath)
        return
    }

    const spec = loadOpenApi()
    const rawOps = findOperationsByProduct(spec, product)
    const ops = deduplicateOperations(rawOps)

    if (ops.length === 0) {
        console.error(`No operations found for product "${product}"`)
        process.exit(1)
    }

    const resolvedOutput = outputPath
        ? path.resolve(MCP_ROOT, outputPath)
        : path.join(DEFINITIONS_DIR, `${product.replace(/-/g, '_')}.yaml`)

    if (fs.existsSync(resolvedOutput)) {
        const validIds = new Set(rawOps.map((op) => op.operationId))
        const { content, matched, lostEnabledTools, droppedDisabledTools } = mergeWithExisting(
            loadCategoryConfig(resolvedOutput),
            ops,
            product,
            validIds
        )
        fs.writeFileSync(resolvedOutput, content)
        process.stdout.write(`${matched} tool(s), ${droppedDisabledTools.length} removed — ${resolvedOutput}\n`)
        reportDroppedDisabledTools(droppedDisabledTools)
        reportLostEnabledTools(lostEnabledTools)
    } else {
        fs.mkdirSync(path.dirname(resolvedOutput), { recursive: true })
        fs.writeFileSync(resolvedOutput, generateFreshYaml(product))
        process.stdout.write(
            `Created ${resolvedOutput} with no tools. ${ops.length} operation(s) found; list them with --candidates.\n`
        )
    }

    formatWithPrettier([resolvedOutput])
}

export { buildAddedTool, findCandidates, mergeWithExisting, renderCategoryYaml }
export type { OpenApiSpec }

function stripExt(filePath: string): string {
    return filePath.replace(/\.[jt]s$/, '')
}

// Tests import this module, so run the CLI only when the script itself is executed.
const isDirectRun =
    typeof process !== 'undefined' &&
    process.argv[1] &&
    stripExt(path.resolve(process.argv[1])) === stripExt(fileURLToPath(import.meta.url))

if (isDirectRun) {
    main()
}
