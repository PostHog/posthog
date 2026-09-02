#!/usr/bin/env tsx
/**
 * Generates per-product agent-context payloads for scene-level PostHog AI integration.
 *
 * Scenes that auto-attach AI context (via `useSceneAgentPanel`) front-load the MCP tool
 * catalog and skill bodies relevant to their product, so the agent can act immediately
 * instead of spending turns on tool discovery and skill reads. The payloads must track
 * the live tool descriptions (actively tuned in mcp/*.yaml) and skill markdown, so they
 * are generated here rather than hand-maintained.
 *
 * Reads:
 * - schema/tool-definitions-all.json (resolved descriptions; produced by generate-tools.ts)
 * - products/<product>/mcp/*.yaml (which tools are enabled, grouped by source file)
 * - products/<product>/skills/<skill>/ markdown
 *
 * Produces:
 * - products/<product>/frontend/generated/agentContext.ts
 *
 * Run via hogli: `hogli build:openapi-scene-tool-context` (also runs as part of
 * `build:openapi`, after `build:openapi-mcp-tools` which produces the tool
 * definitions this reads). See `hogli.yaml`.
 */
import { spawnSync } from 'node:child_process'
import * as fs from 'node:fs'
import * as path from 'node:path'
import { parse as parseYaml } from 'yaml'

const MCP_ROOT = path.resolve(__dirname, '..')
const REPO_ROOT = path.resolve(MCP_ROOT, '../..')
const ALL_DEFINITIONS_PATH = path.resolve(MCP_ROOT, 'schema/tool-definitions-all.json')

interface ToolSourceConfig {
    constName: string
    yamlPath: string
    /**
     * Tools registered directly in services/mcp/src/tools (no `enabled:` entry in the YAML), which
     * YAML-derived membership would silently omit. Resolution still requires each name to exist in
     * tool-definitions-all.json, so a renamed or removed tool fails the build instead of shrinking
     * the catalog.
     */
    extraTools?: string[]
}

interface SkillSourceConfig {
    constName: string
    skillDir: string
    /** Markdown files to embed, in order. The first file's YAML frontmatter is stripped. */
    files: string[]
}

interface SceneContextConfig {
    /** Generated frontend files belong under products/<product>/frontend/generated/. */
    output: string
    tools: ToolSourceConfig[]
    skills: SkillSourceConfig[]
}

const CONFIGS: SceneContextConfig[] = [
    {
        output: 'products/workflows/frontend/generated/agentContext.ts',
        tools: [
            {
                constName: 'WORKFLOWS_MCP_TOOLS',
                yamlPath: 'products/workflows/mcp/tools.yaml',
                extraTools: [
                    'workflows-enable',
                    'workflows-archive',
                    'workflows-blast-radius',
                    'workflows-run-batch',
                    'workflows-schedule-create',
                ],
            },
            { constName: 'EMAIL_TEMPLATE_MCP_TOOLS', yamlPath: 'products/workflows/mcp/email_templates.yaml' },
        ],
        skills: [
            {
                constName: 'BUILDING_WORKFLOWS_SKILL',
                skillDir: 'products/workflows/skills/building-workflows',
                files: ['SKILL.md', 'references/graph-schema.md'],
            },
            {
                constName: 'DESIGNING_EMAIL_TEMPLATES_SKILL',
                skillDir: 'products/workflows/skills/designing-email-templates',
                files: ['SKILL.md', 'references/unlayer-design-json.md', 'references/design-guidelines.md'],
            },
        ],
    },
]

interface ToolDefinition {
    description?: string
    feature?: string
}

function enabledToolNames(yamlPath: string): string[] {
    const parsed = parseYaml(fs.readFileSync(path.resolve(REPO_ROOT, yamlPath), 'utf8')) as {
        tools?: Record<string, { enabled?: boolean }>
    }
    return Object.entries(parsed.tools ?? {})
        .filter(([, config]) => config?.enabled === true)
        .map(([name]) => name)
}

interface FrontmatterResult {
    meta: { name?: string; description?: string }
    body: string
}

function splitFrontmatter(markdown: string): FrontmatterResult {
    const match = markdown.match(/^---\n([\s\S]*?)\n---\n/)
    if (!match?.[1]) {
        return { meta: {}, body: markdown }
    }
    return {
        meta: parseYaml(match[1]) as FrontmatterResult['meta'],
        body: markdown.slice(match[0].length),
    }
}

function renderToolConst(config: ToolSourceConfig, definitions: Record<string, ToolDefinition>): string {
    const { constName, yamlPath } = config
    const names = [...enabledToolNames(yamlPath), ...(config.extraTools ?? [])]
    const entries = names.map((name) => {
        const definition = definitions[name]
        if (!definition?.description) {
            throw new Error(
                `tool "${name}" is enabled in ${yamlPath} (or listed in extraTools) but has no description in ` +
                    'tool-definitions-all.json — run `hogli build:openapi-mcp-tools` first'
            )
        }
        return (
            '    {\n' +
            `        name: ${JSON.stringify(name)},\n` +
            `        description: ${JSON.stringify(definition.description)},\n` +
            '    },'
        )
    })
    return `export const ${constName}: McpToolSummary[] = [\n${entries.join('\n')}\n]\n`
}

function renderSkillConst(config: SkillSourceConfig): string {
    const [firstFile, ...restFiles] = config.files
    if (!firstFile) {
        throw new Error(`skill config ${config.constName} has no files`)
    }
    const first = splitFrontmatter(fs.readFileSync(path.resolve(REPO_ROOT, config.skillDir, firstFile), 'utf8'))
    const skillName = first.meta.name ?? path.basename(config.skillDir)
    const parts = [
        first.body.trim(),
        ...restFiles.map((file) => fs.readFileSync(path.resolve(REPO_ROOT, config.skillDir, file), 'utf8').trim()),
    ]
    return (
        `export const ${config.constName}: EmbeddedSkill = {\n` +
        `    name: ${JSON.stringify(skillName)},\n` +
        `    description: ${JSON.stringify(first.meta.description ?? '')},\n` +
        `    content: ${JSON.stringify(parts.join('\n\n'))},\n` +
        '}\n'
    )
}

const HEADER =
    '// AUTO-GENERATED by services/mcp/scripts/build-scene-tool-context.ts.\n' +
    '// Regenerate with `hogli build:openapi`. Do not edit.\n' +
    '//\n' +
    '// Static agent-context payloads for scene-level PostHog AI integration: the enabled\n' +
    '// MCP tool catalog (names + live descriptions) and embedded skill bodies, attached\n' +
    '// as context by `useSceneAgentPanel` callers so the agent starts with everything it\n' +
    '// needs instead of discovering tools and reading skills at run time.\n' +
    '\n' +
    'export interface McpToolSummary {\n' +
    '    name: string\n' +
    '    description: string\n' +
    '}\n' +
    '\n' +
    'export interface EmbeddedSkill {\n' +
    '    name: string\n' +
    '    description: string\n' +
    '    content: string\n' +
    '}\n'

function main(): void {
    const definitions = JSON.parse(fs.readFileSync(ALL_DEFINITIONS_PATH, 'utf8')) as Record<string, ToolDefinition>

    for (const config of CONFIGS) {
        const sections = [
            HEADER,
            ...config.tools.map((tool) => renderToolConst(tool, definitions)),
            ...config.skills.map((skill) => renderSkillConst(skill)),
        ]
        const output = sections.join('\n')
        const outputPath = path.resolve(REPO_ROOT, config.output)
        const existing = fs.existsSync(outputPath) ? fs.readFileSync(outputPath, 'utf8') : null
        fs.writeFileSync(outputPath, output)
        // JSON.stringify emits double quotes; run the repo formatter so the committed file is oxfmt-stable.
        const format = spawnSync(path.join(REPO_ROOT, 'node_modules/.bin/oxfmt'), [config.output], {
            cwd: REPO_ROOT,
            stdio: 'inherit',
        })
        if (format.status !== 0) {
            throw new Error(`oxfmt failed on ${config.output}`)
        }
        const formatted = fs.readFileSync(outputPath, 'utf8')
        // eslint-disable-next-line no-console
        console.log(formatted === existing ? `${outputPath} already up to date` : `wrote ${outputPath}`)
    }
}

main()
