import { RESOURCE_URI_META_KEY } from '@modelcontextprotocol/ext-apps/server'
import type { Tool as McpTool } from '@modelcontextprotocol/sdk/types.js'

import { hasScope } from '@/lib/api'
import { isPostHogCodeConsumer } from '@/lib/client-detection'
import type { QueryToolInfo } from '@/lib/instructions'
import { HOGQL_GUIDE_ID, type InstructionsContext, InstructionsFormatter } from '@/lib/instructions-formatter'
import { isChatGptAppConnection } from '@/lib/oauth-constants'
import { formatPrompt } from '@/lib/utils'
import { RENDER_UI_RESOURCE_URI } from '@/resources/ui-apps.generated'
import { ProjectSkillCatalog } from '@/skills/project-skill-catalog'
import type { SkillCatalog } from '@/skills/skill-catalog'
import EXECUTE_SQL_PROMPT from '@/templates/execute-sql-prompt.md'
import EXECUTE_SQL_REFERENCE from '@/templates/execute-sql-reference.md'
import CATALOG_TRUST_DISCOVERY from '@/templates/sections/catalog-trust-discovery.md'
import HOGQL_ESSENTIALS from '@/templates/sections/hogql-essentials.md'
import METRIC_DISCOVERY from '@/templates/sections/metric-discovery.md'
import SCHEMA_DISCOVERY from '@/templates/sections/schema-discovery.md'
import { EXEC_TOOL_ANNOTATIONS } from '@/tools/exec'
import { ExecLearnCatalog } from '@/tools/exec-learn'
import {
    getRenderableToolNames,
    makeRenderUiSchema,
    RENDER_UI_TOOL_ANNOTATIONS,
    RENDER_UI_TOOL_NAME,
    RENDER_UI_TOOL_TITLE,
    renderUiDescription,
} from '@/tools/render-ui'
import { getToolDefinition } from '@/tools/toolDefinitions'

import { trackSkillInvoked } from './analytics'
import { MCP_EXEC_SKILLS_FEATURE_FLAG } from './constants'
import { getEffectiveMCPClientContext } from './mcp-context'
import type { ResolvedState } from './request-state-resolver'
import { toMcpInputSchema } from './tool-catalog'

export type ExecToolState = Pick<
    ResolvedState,
    | 'renderUiEnabled'
    | 'businessKnowledgeContent'
    | 'clientProfile'
    | 'requestContext'
    | 'sessionContext'
    | 'toolFeatureFlags'
> & { allTools: readonly { name: string }[] }

/** Presence of this tool is the runtime signal that the notebook cell surface
 *  (the `revamped-py-notebooks` flag) is live for this client. */
const NOTEBOOK_ADD_CELL_TOOL = 'notebooks-add-cell'
const NOTEBOOK_RUN_TOOL = 'notebooks-run'
const DOCS_SEARCH_TOOL = 'docs-search'
const BUSINESS_KNOWLEDGE_SEARCH_TOOL = 'business-knowledge-documents-search'
const BUSINESS_KNOWLEDGE_REPO_SEARCH_TOOL = 'business-knowledge-repositories-search'

// Human comment, not AI slop. Version 2.0.0 of the PostHog app for ChatGPT and Codex started
// requesting `llm_skill:read`, but existing connections never got re-prompted for it, so their
// agents hit a warning they can't act on. Telling them to "reconnect with that scope" doesn't
// work there, since the app picks the scopes, so this nudges them to the thing that does:
// disconnect the app and connect it again. Can be removed after 2027-01-01.
function projectSkillsScopeReason(oauthClientId: string | undefined): string {
    if (isChatGptAppConnection(oauthClientId)) {
        return 'This connection is missing the llm_skill:read scope. A new connection to the PostHog app includes it: disconnect the PostHog app in ChatGPT or Codex and connect it again to read project skills.'
    }
    return 'This connection is missing the llm_skill:read scope. Reconnect with that scope to read project skills.'
}

export class InstructionsBuilder {
    private readonly formatter: InstructionsFormatter
    private readonly guidelines: string

    constructor(guidelines: string, formatter?: InstructionsFormatter) {
        this.guidelines = guidelines
        this.formatter = formatter ?? new InstructionsFormatter()
    }

    build(state: ResolvedState): string {
        const supportsInstructions = state.clientProfile.capabilities.supportsInstructions
        if (!supportsInstructions) {
            return ''
        }

        const ctx = this.buildContext(state)
        if (state.useSingleExec) {
            return this.formatter.buildExecInstructions(ctx)
        }
        return this.formatter.buildToolsInstructions(ctx)
    }

    buildContext(state: ExecToolState): InstructionsContext {
        return {
            guidelines: this.guidelines,
            tools: state.allTools.map((t) => ({
                name: t.name,
                category: getToolDefinition(t.name).category,
            })),
            queryTools: state.allTools
                .filter((t) => t.name.startsWith('query-'))
                .map((t) => {
                    const def = getToolDefinition(t.name)
                    return {
                        name: t.name,
                        title: def.title,
                        ...(def.system_prompt_hint ? { systemPromptHint: def.system_prompt_hint } : {}),
                    } as QueryToolInfo
                }),
            renderUiEnabled: state.renderUiEnabled,
            notebookCellsEnabled: state.allTools.some((tool) => tool.name === NOTEBOOK_ADD_CELL_TOOL),
            notebookRunEnabled: state.allTools.some((tool) => tool.name === NOTEBOOK_RUN_TOOL),
            docsSearchEnabled: state.allTools.some((tool) => tool.name === DOCS_SEARCH_TOOL),
            businessKnowledgeContent: state.businessKnowledgeContent,
        }
    }

    buildExecToolEntry(state: ExecToolState): McpTool {
        const commandReference = this.buildExecCommandReference(state)
        const ExecSchema = { command: { type: 'string', description: commandReference } }

        return {
            name: 'exec',
            title: 'Execute PostHog command',
            description: this.buildExecToolDescription(state),
            inputSchema: { type: 'object', properties: ExecSchema, required: ['command'] },
            annotations: { ...EXEC_TOOL_ANNOTATIONS },
        }
    }

    buildRenderUiToolEntry(tools: McpTool[]): McpTool | null {
        const toolNames = getRenderableToolNames(tools)
        if (toolNames.length === 0) {
            return null
        }
        return {
            name: RENDER_UI_TOOL_NAME,
            title: RENDER_UI_TOOL_TITLE,
            description: renderUiDescription(toolNames),
            // OpenAI caches this schema across accounts; authorization stays in the executor.
            inputSchema: toMcpInputSchema(makeRenderUiSchema(toolNames as [string, ...string[]])),
            annotations: { ...RENDER_UI_TOOL_ANNOTATIONS },
            // Advertise the umbrella UI resource so MCP Apps hosts (e.g. Claude) discover
            // render-ui as renderable from `tools/list` and mount its iframe. Both the
            // modern and legacy keys are emitted since this entry isn't normalized downstream.
            _meta: {
                ui: { resourceUri: RENDER_UI_RESOURCE_URI },
                [RESOURCE_URI_META_KEY]: RENDER_UI_RESOURCE_URI,
            },
        }
    }

    buildExecCommandReference(state: ExecToolState): string {
        const { guidesEnabled, skillsEnabled } = this.getExecLearnCapabilities(state)
        const ctx = this.buildContext(state)
        const claudeChat = state.clientProfile.isClaudeChatHost()
        // Claude web/desktop stay on the compact reference without `learn`, because the full one overflows their schema cap.
        if (claudeChat || guidesEnabled) {
            return this.formatter.buildCompactExecCommandReference(ctx, {
                claudeChat,
                learnEnabled: guidesEnabled || skillsEnabled,
                skillsEnabled,
            })
        }
        return this.formatter.buildExecCommandReference(ctx)
    }

    buildExecLearnCatalog(state: ResolvedState, skills: SkillCatalog | undefined): ExecLearnCatalog | undefined {
        const { guidesEnabled, skillsEnabled } = this.getExecLearnCapabilities(state)
        if (!guidesEnabled && !skillsEnabled) {
            return undefined
        }
        const guides = guidesEnabled ? this.formatter.buildExecLearnGuides(this.buildContext(state)) : []
        const canReadProjectSkills = skillsEnabled && hasScope(state.apiKeyScopes, 'llm_skill:read')
        // The catalog (and this closure) is rebuilt per request, so this Set dedupes
        // within one exec command — a 5-file batch of one skill fires a single event,
        // while separate commands each still count.
        const invokedIdentifiers = new Set<string>()
        return new ExecLearnCatalog(
            guides,
            skillsEnabled
                ? {
                      posthog: skills,
                      project: canReadProjectSkills ? new ProjectSkillCatalog(state.context) : undefined,
                      projectUnavailableReason: canReadProjectSkills
                          ? undefined
                          : projectSkillsScopeReason(state.oauthClientId),
                  }
                : undefined,
            (invocation) => {
                const identifier = `${invocation.source}:${invocation.skill}`
                if (invokedIdentifiers.has(identifier)) {
                    return
                }
                invokedIdentifiers.add(identifier)
                void trackSkillInvoked(state, invocation)
            }
        )
    }

    buildExecToolDescription(state?: ExecToolState): string {
        const skillsEnabled = state ? this.getExecLearnCapabilities(state).skillsEnabled : false
        const docsSearchEnabled = state?.allTools.some(({ name }) => name === DOCS_SEARCH_TOOL)
        const businessKnowledgeSearchEnabled = state?.allTools.some(
            ({ name }) => name === BUSINESS_KNOWLEDGE_SEARCH_TOOL
        )
        const businessKnowledgeRepoSearchEnabled = state?.allTools.some(
            ({ name }) => name === BUSINESS_KNOWLEDGE_REPO_SEARCH_TOOL
        )
        return this.formatter.buildExecToolDescription({
            skillsEnabled,
            docsSearchEnabled,
            businessKnowledgeSearchEnabled,
            businessKnowledgeRepoSearchEnabled,
            businessKnowledgeContent: state?.businessKnowledgeContent,
        })
    }

    execSkillsEnabled(state: ExecToolState): boolean {
        return this.getExecLearnCapabilities(state).skillsEnabled
    }

    getGuidelines(): string {
        return this.guidelines
    }

    formatExecuteSqlDescription(state?: ExecToolState): string {
        // Metric discovery leads the splice so catalog-first routing still precedes
        // raw schema discovery, without displacing the tool's own intro line.
        const schemaDiscovery = `${METRIC_DISCOVERY.trim()}\n\n${SCHEMA_DISCOVERY.trim()}\n\n${CATALOG_TRUST_DISCOVERY.trim()}`
        const referencePointer = state ? this.hogqlReferencePointer(state) : undefined
        return formatPrompt(EXECUTE_SQL_PROMPT, {
            hogql: referencePointer
                ? formatPrompt(HOGQL_ESSENTIALS, { reference_pointer: referencePointer })
                : this.guidelines.trim(),
            schema_discovery: schemaDiscovery,
            reference: referencePointer ? '' : EXECUTE_SQL_REFERENCE.trim(),
        })
    }

    private hogqlReferencePointer(state: ExecToolState): string | undefined {
        const { mcpConsumer } = getEffectiveMCPClientContext(state.requestContext, state.sessionContext)
        if (mcpConsumer === 'plugin' || state.requestContext.bundledSkills) {
            return 'The full HogQL reference is in your bundled `querying-posthog-data` skill: read its `references/guidelines.md`, and its `models-*.md` references for `posthog.ai_events`, `logs`, `posthog.trace_spans`, and `posthog.metrics`.'
        }
        if (this.getExecLearnCapabilities(state).guidesEnabled) {
            return `Run \`learn ${HOGQL_GUIDE_ID}\` for the full HogQL reference, with examples and the observability and LLM tables.`
        }
        return undefined
    }

    private getExecLearnCapabilities(state: ExecToolState): { guidesEnabled: boolean; skillsEnabled: boolean } {
        const clientContext = getEffectiveMCPClientContext(state.requestContext, state.sessionContext)
        // The plugin and PostHog Code bundle their own skills, so learn never serves skills to them.
        // The plugin still gets the built-in guides, which carry server guidance rather than skills.
        if (isPostHogCodeConsumer(clientContext.mcpConsumer)) {
            return { guidesEnabled: false, skillsEnabled: false }
        }
        if (clientContext.mcpConsumer === 'plugin') {
            return { guidesEnabled: true, skillsEnabled: false }
        }
        return {
            guidesEnabled: true,
            skillsEnabled: state.toolFeatureFlags?.[MCP_EXEC_SKILLS_FEATURE_FLAG] === true,
        }
    }
}
