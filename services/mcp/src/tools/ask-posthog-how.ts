import type { Tool as McpTool } from '@modelcontextprotocol/sdk/types.js'
import { z } from 'zod'

import { toMcpInputSchema } from '@/hono/tool-catalog'
import type { SkillCatalog } from '@/skills/skill-catalog'

import { searchToolsRanked } from './tool-search'
import type { Tool, ZodObjectAny } from './types'

export const ASK_POSTHOG_HOW_TOOL_NAME = 'ask-posthog-how'

const MAX_RECIPE_TOOLS = 5
const MAX_RECIPE_SKILLS = 3

// Ranking matches substrings across every tool description, so these words would rank tools
// by how long their descriptions are rather than by what the user asked for.
const STOP_WORDS = new Set([
    'about',
    'and',
    'are',
    'can',
    'compared',
    'does',
    'each',
    'every',
    'for',
    'from',
    'have',
    'how',
    'including',
    'into',
    'last',
    'many',
    'most',
    'one',
    'other',
    'our',
    'over',
    'right',
    'show',
    'tell',
    'than',
    'that',
    'the',
    'their',
    'them',
    'there',
    'this',
    'what',
    'when',
    'where',
    'which',
    'who',
    'why',
    'will',
    'with',
    'you',
    'your',
])

// Without one of these the user is asking a question, so the recipe offers only read-only tools.
const CHANGE_WORDS = new Set([
    'add',
    'archive',
    'change',
    'create',
    'delete',
    'disable',
    'edit',
    'enable',
    'end',
    'invite',
    'launch',
    'make',
    'pause',
    'remove',
    'rename',
    'save',
    'set',
    'ship',
    'start',
    'stop',
    'update',
])

export const ASK_POSTHOG_HOW_INSTRUCTIONS = `This server answers questions about the user's PostHog data.
Before anything else, call \`${ASK_POSTHOG_HOW_TOOL_NAME}\` with the user's goal in their own words.
It returns a recipe: the \`exec\` commands that answer the goal, the arguments each one needs, and the skills to load first.
Load the listed skills, then run the recipe with \`exec\`. Run \`info <tool>\` through \`exec\` before a \`call\` when you need the full argument schema.
Call \`${ASK_POSTHOG_HOW_TOOL_NAME}\` again when the recipe does not fit what you find.`

export const AskPostHogHowSchema = z.object({
    intent: z
        .string()
        .trim()
        .min(1)
        .describe("What the user wants to find out or change in PostHog, in the user's own words."),
})

export interface RecipeStep {
    tool: string
    title: string
    required_arguments: string[]
    exec: string
}

export interface Recipe {
    steps: RecipeStep[]
    skills: { name: string; description: string }[]
    note: string
}

export function buildAskPostHogHowEntry(inputSchema: McpTool['inputSchema']): McpTool {
    return {
        name: ASK_POSTHOG_HOW_TOOL_NAME,
        title: 'Ask PostHog how',
        description:
            "Ask how to do something in PostHog before you start. Pass the user's goal in their own words. " +
            'Returns the exec commands that answer it, the arguments each command needs, and the skills to load first. ' +
            'You run the commands yourself with exec.',
        inputSchema,
        annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    }
}

/** Plural and stop words removed, so "Which experiments are running" ranks on "experiment" and "running". */
export function intentKeywords(intent: string): string[] {
    const words = intent
        .toLowerCase()
        .split(/[^a-z0-9_$-]+/)
        .filter((word) => word.length >= 3 && !STOP_WORDS.has(word))
        .map((word) => (word.length > 4 && word.endsWith('s') && !word.endsWith('ss') ? word.slice(0, -1) : word))
    return [...new Set(words)]
}

function requiredArguments(tool: Tool<ZodObjectAny>): string[] {
    try {
        const { required } = toMcpInputSchema(tool.schema)
        return Array.isArray(required) ? required : []
    } catch {
        return []
    }
}

/**
 * Picks the tools and skills that match the user's goal from what this connection may use.
 * A ranked keyword match, not a model call: the MCP server has no LLM client of its own.
 */
export function buildRecipe(intent: string, tools: readonly Tool<ZodObjectAny>[], skills?: SkillCatalog): Recipe {
    const keywords = intentKeywords(intent)
    const query = keywords.join(' ')
    const changes = intent
        .toLowerCase()
        .split(/[^a-z]+/)
        .some((word) => CHANGE_WORDS.has(word))
    const candidates = changes ? tools : tools.filter((tool) => tool.annotations?.readOnlyHint === true)
    const toolsByName = new Map(candidates.map((tool) => [tool.name, tool]))
    const steps = searchToolsRanked(candidates, query)
        // A tool named after the goal beats one that only mentions more of its words.
        .sort((a, b) => Number(b.fields.includes('name')) - Number(a.fields.includes('name')))
        .slice(0, MAX_RECIPE_TOOLS)
        .flatMap((match) => {
            const tool = toolsByName.get(match.name)
            if (!tool) {
                return []
            }
            const required = requiredArguments(tool)
            const args = Object.fromEntries(required.map((name) => [name, `<${name}>`]))
            return [
                {
                    tool: tool.name,
                    title: tool.title,
                    required_arguments: required,
                    exec: `call ${tool.name} ${JSON.stringify(args)}`,
                },
            ]
        })
    const matchedSkills =
        skills && query
            ? skills
                  .searchResults(query)
                  .slice(0, MAX_RECIPE_SKILLS)
                  .map((result) => ({ name: result.identifier, description: result.description }))
            : []
    return {
        steps,
        skills: matchedSkills,
        note:
            steps.length > 0
                ? 'Steps are ranked by how well each tool matches the goal. Use the first one that answers it; replace each <argument> with a real value.'
                : 'No tool matched this goal. Rephrase it with the PostHog product it concerns, or run `search <words>` through exec.',
    }
}
