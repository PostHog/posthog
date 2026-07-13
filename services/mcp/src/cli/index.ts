#!/usr/bin/env node
import { AnalyticsEvent } from '@/lib/posthog/analytics'
import { createExecTool } from '@/tools/exec'
import type { Context, Tool, ZodObjectAny } from '@/tools/types'

import { buildAgentHelp } from './agent-help'
import { installAgentsMdSnippet } from './agents-md'
import { takeOption } from './args'
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
call [--json] [--confirm] <tool_name> <json_input>`

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
  posthog-cli api skill list [--json]
  posthog-cli api skill install [--force] <skill-id>
  posthog-cli api agents-md install [--path AGENTS.md]

Destructive tools require --confirm when executed. Use --dry-run before mutations.
Agents: run \`posthog-cli api --agent-help\` and load the output into context before anything else.`
}

function takeFlag(args: string[], flag: string): boolean {
    const index = args.indexOf(flag)
    if (index === -1) {
        return false
    }
    args.splice(index, 1)
    return true
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
        { requireDestructiveConfirmation: true }
    )

    return { execTool, tools }
}

async function buildExec(config: CliConfig = resolveCliConfig()): Promise<BuiltExec> {
    const context = await buildCliContext(config)
    const aiConsentGiven = await context.stateManager.getAiConsentGiven()
    const tools = getCliTools({ aiConsentGiven })
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
                ...(properties.error_message ? { error_message: properties.error_message } : {}),
            }
            void context.trackEvent(AnalyticsEvent.MCP_TOOL_CALL, toolCallProperties)
        },
        [],
        { requireDestructiveConfirmation: true }
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
    if (command.startsWith('call ')) {
        requireApiKey(config)
    }
    const { execTool, context } = await buildExec(config)
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
