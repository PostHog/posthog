#!/usr/bin/env node
import { AnalyticsEvent } from '@/lib/posthog/analytics'
import { createCodeExecutionDiscovery } from '@/tools/code-exec/runtime'
import { createExecTool, parseExecVerb } from '@/tools/exec'
import type { Context, Tool, ZodObjectAny } from '@/tools/types'

import { buildAgentHelp } from './agent-help'
import { installAgentsMdSnippet } from './agents-md'
import { takeFlag, takeOption } from './args'
import {
    buildCliCodeExecution,
    parseRunArgs,
    resolveCliSessionScopes,
    resolveRunSource,
    runCliApply,
    runCliRun,
    runCliTypes,
} from './code-exec'
import type { CliConfig } from './config'
import { resolveCliConfig, requireApiKey } from './config'
import { buildCliContext } from './context'
import { installSkill, listSkills } from './skills'
import { getCliTools } from './tools'

const COMMAND_REFERENCE = `CLI-style command string. Supported commands:
tools
search <regex_pattern>
info [--json] <tool_name>
schema <tool_name> [field_path]
call [--json] [--confirm] <tool_name> <json_input>
types <query | TypeName... | domain.method | domain>
run <typescript source>
apply <plan-id>
sql <hogql>`

interface BuiltExec {
    context: Context
    execTool: Tool<ZodObjectAny>
    tools: Tool<ZodObjectAny>[]
}

interface BuiltStaticExec {
    execTool: Tool<ZodObjectAny>
    tools: Tool<ZodObjectAny>[]
}

function usage(): string {
    return `PostHog agent CLI

Usage:
  posthog-cli api --agent-help
  posthog-cli api tools
  posthog-cli api search <regex>
  posthog-cli api info [--json] <tool>
  posthog-cli api schema <tool> [field.path]
  posthog-cli api call [--json] [--dry-run] [--confirm] <tool> '<json>'
  posthog-cli api types <query | TypeName | domain.method | domain>
  posthog-cli api run [--yes] [--file <path> | -] ['<ts source>']
  posthog-cli api apply <plan-id>
  posthog-cli api sql '<hogql>'
  posthog-cli api skill list [--json]
  posthog-cli api skill install [--force] <skill-id>
  posthog-cli api agents-md install [--path AGENTS.md]

Destructive tools require --confirm when executed. Use --dry-run before mutations.
\`run\` executes a TypeScript script against @posthog/sdk on this machine; a mutating
script returns a plan — review it, then \`apply <plan-id>\` (or pass --yes to apply
immediately). \`types\` searches the bundled SDK index and needs no API key.
Agents: run \`posthog-cli api --agent-help\` and load the output into context before anything else.`
}

function printResult(result: unknown): void {
    if (typeof result === 'string') {
        process.stdout.write(result.endsWith('\n') ? result : `${result}\n`)
        return
    }
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`)
}

function buildStaticExec(): BuiltStaticExec {
    const tools = getCliTools()
    const execTool = createExecTool(
        tools,
        undefined,
        'Execute a PostHog CLI command',
        COMMAND_REFERENCE,
        'posthog-cli',
        undefined,
        [],
        {
            requireDestructiveConfirmation: true,
            // Keyless static discovery from the bundled index: '*' short-circuits
            // scope checks so `types` renders without misleading "missing on this
            // token" annotations (spec §4.8 — `types` works without an API key).
            codeExecutionDiscovery: createCodeExecutionDiscovery({ sessionScopes: ['*'] }),
        }
    )

    return { execTool, tools }
}

async function buildExec(config: CliConfig = resolveCliConfig(), command?: string): Promise<BuiltExec> {
    const context = await buildCliContext(config)
    const aiConsentGiven = await context.stateManager.getAiConsentGiven()
    const tools = getCliTools({ aiConsentGiven })
    // Same verb dimension the hosted exec stamps on its events (spec §4.6 Phase 0),
    // so CLI adoption lands in the same dashboards.
    const execVerb = command === undefined ? undefined : parseExecVerb(command)
    // Exec-string parity for the code-execution verbs (spec §4.8). Real scopes
    // only matter to `types` annotations — every other verb ignores them, so
    // skip the extra key-introspection round trip unless the verb needs it.
    const sessionScopes = execVerb === 'types' && config.apiKey ? await resolveCliSessionScopes(context) : ['*']
    const codeExecution = buildCliCodeExecution(context, sessionScopes)
    const execTool = createExecTool(
        tools,
        context,
        'Execute a PostHog CLI command',
        COMMAND_REFERENCE,
        'posthog-cli',
        (toolName, properties) => {
            const toolCallProperties = {
                tool_name: toolName,
                $mcp_tool_name: toolName,
                $mcp_duration_ms: properties.duration_ms,
                $mcp_is_error: !properties.success,
                output_format: properties.output_format,
                ...(execVerb !== undefined ? { $mcp_exec_verb: execVerb } : {}),
                ...(properties.error_message ? { error_message: properties.error_message } : {}),
            }
            void context.trackEvent(AnalyticsEvent.MCP_TOOL_CALL, toolCallProperties)
        },
        [],
        {
            requireDestructiveConfirmation: true,
            codeExecutionDiscovery: codeExecution.discovery,
            codeExecutionRuntime: codeExecution.runtime,
        }
    )

    return { context, execTool, tools }
}

function buildAgentHelpForStaticCatalog(): string {
    return buildAgentHelp(getCliTools())
}

async function runStaticExecCommand(command: string): Promise<void> {
    const { execTool } = buildStaticExec()
    const result = await execTool.handler(undefined as unknown as Context, { command })
    printResult(result)
}

async function runExecCommand(command: string): Promise<void> {
    const config = resolveCliConfig()
    if (command.startsWith('call ') || command.startsWith('sql ')) {
        requireApiKey(config)
    }
    const { execTool, context } = await buildExec(config, command)
    const result = await execTool.handler(context, { command })
    printResult(result)
}

async function runDryCall(args: string[]): Promise<void> {
    const forceJson = takeFlag(args, '--json')
    const confirmed = takeFlag(args, '--confirm')
    const toolName = args.shift()
    const jsonBody = args.length > 0 ? args.join(' ') : '{}'
    if (!toolName) {
        throw new Error('Usage: posthog-cli api call --dry-run [--json] [--confirm] <tool> <json>')
    }

    const { tools } = buildStaticExec()
    const tool = tools.find((candidate) => candidate.name === toolName)
    if (!tool) {
        throw new Error(`Unknown tool: "${toolName}". Run "posthog-cli api search <term>".`)
    }

    let parsed: Record<string, unknown>
    try {
        parsed = jsonBody ? (JSON.parse(jsonBody) as Record<string, unknown>) : {}
    } catch (error) {
        const detail = error instanceof Error ? error.message : String(error)
        throw new Error(`Invalid JSON input: ${detail}`)
    }

    const validation = tool.schema.safeParse(parsed)
    printResult({
        dryRun: true,
        tool: tool.name,
        title: tool.title,
        annotations: tool.annotations,
        outputFormat: forceJson ? 'json' : 'text',
        destructiveConfirmationRequired: tool.annotations.destructiveHint && !confirmed,
        valid: validation.success,
        ...(validation.success ? { input: validation.data } : { error: validation.error.message }),
    })
}

async function runSkillCommand(args: string[]): Promise<void> {
    const subcommand = args.shift()
    switch (subcommand) {
        case 'list': {
            const json = takeFlag(args, '--json')
            const skills = await listSkills()
            if (json) {
                printResult(skills)
                return
            }
            for (const skill of skills) {
                process.stdout.write(`${skill.id}\t${skill.name}\n`)
            }
            return
        }
        case 'install': {
            const force = takeFlag(args, '--force')
            const skillId = args.shift()
            if (!skillId) {
                throw new Error('Usage: posthog-cli api skill install [--force] <skill-id>')
            }
            printResult(await installSkill(skillId, { force }))
            return
        }
        default:
            throw new Error('Usage: posthog-cli api skill list|install')
    }
}

async function runAgentsMdCommand(args: string[]): Promise<void> {
    const subcommand = args.shift()
    if (subcommand !== 'install') {
        throw new Error('Usage: posthog-cli api agents-md install [--path AGENTS.md]')
    }
    const filePath = takeOption(args, '--path')
    const installedPath = await installAgentsMdSnippet(filePath ? { filePath } : {})
    printResult({ installed: true, path: installedPath })
}

async function main(): Promise<void> {
    const args = process.argv.slice(2)
    const command = args.shift()

    if (!command || command === 'help' || command === '--help' || command === '-h') {
        process.stdout.write(`${usage()}\n`)
        return
    }

    if (command === 'agent-help' || command === '--agent-help') {
        process.stdout.write(`${buildAgentHelpForStaticCatalog()}\n`)
        return
    }

    switch (command) {
        case 'tools':
            await runStaticExecCommand('tools')
            return
        case 'search':
            await runStaticExecCommand(`search ${args.join(' ')}`)
            return
        case 'info': {
            const json = takeFlag(args, '--json')
            const toolName = args.shift()
            if (!toolName) {
                throw new Error('Usage: posthog-cli api info [--json] <tool>')
            }
            await runStaticExecCommand(`info ${json ? '--json ' : ''}${toolName}`)
            return
        }
        case 'schema': {
            const toolName = args.shift()
            if (!toolName) {
                throw new Error('Usage: posthog-cli api schema <tool> [field.path]')
            }
            await runStaticExecCommand(`schema ${toolName}${args[0] ? ` ${args[0]}` : ''}`)
            return
        }
        case 'call': {
            const dryRun = takeFlag(args, '--dry-run')
            if (dryRun) {
                await runDryCall(args)
                return
            }
            const json = takeFlag(args, '--json')
            const confirmed = takeFlag(args, '--confirm')
            const toolName = args.shift()
            const jsonBody = args.length > 0 ? args.join(' ') : '{}'
            if (!toolName) {
                throw new Error('Usage: posthog-cli api call [--json] [--dry-run] [--confirm] <tool> <json>')
            }
            await runExecCommand(`call ${json ? '--json ' : ''}${confirmed ? '--confirm ' : ''}${toolName} ${jsonBody}`)
            return
        }
        case 'types': {
            const query = args.join(' ').trim()
            if (!query) {
                throw new Error('Usage: posthog-cli api types <query | TypeName | domain.method | domain>')
            }
            const config = resolveCliConfig()
            if (!config.apiKey) {
                // Fully offline: the bundled discovery index, no context, no analytics —
                // matching the static tools/search/info/schema commands.
                printResult(await createCodeExecutionDiscovery({ sessionScopes: ['*'] }).types(query))
                return
            }
            const context = await buildCliContext(config)
            const { discovery } = buildCliCodeExecution(context, await resolveCliSessionScopes(context))
            await runCliTypes({ context, print: printResult }, discovery, query)
            return
        }
        case 'run': {
            const invocation = parseRunArgs(args, { stdinIsTty: process.stdin.isTTY === true })
            const config = resolveCliConfig()
            requireApiKey(config)
            const source = await resolveRunSource(invocation.source)
            if (!source.trim()) {
                throw new Error('run: the script source is empty')
            }
            const context = await buildCliContext(config)
            const { runtime } = buildCliCodeExecution(context, ['*'])
            await runCliRun({ context, print: printResult }, runtime, { source, yes: invocation.yes })
            return
        }
        case 'apply': {
            // Join the remaining words: the id is a three-word phrase the user
            // may type unquoted (`apply cat assistant tree`), and the shared
            // normalizePlanPhrase canonicalizes exactly that form.
            const planId = args.join(' ').trim()
            if (!planId) {
                throw new Error('Usage: posthog-cli api apply <plan-id>')
            }
            const config = resolveCliConfig()
            requireApiKey(config)
            const context = await buildCliContext(config)
            const { runtime } = buildCliCodeExecution(context, ['*'])
            await runCliApply({ context, print: printResult }, runtime, planId)
            return
        }
        case 'sql': {
            const query = args.join(' ').trim()
            if (!query) {
                throw new Error("Usage: posthog-cli api sql '<hogql>'")
            }
            await runExecCommand(`sql ${query}`)
            return
        }
        case 'skill':
            await runSkillCommand(args)
            return
        case 'agents-md':
            await runAgentsMdCommand(args)
            return
        default:
            throw new Error(`Unknown command "${command}".\n\n${usage()}`)
    }
}

main().catch((error: unknown) => {
    const message = error instanceof Error ? error.message : String(error)
    process.stderr.write(`Error: ${message}\n`)
    process.exit(1)
})
