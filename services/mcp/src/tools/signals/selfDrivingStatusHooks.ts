import { isRecord } from '@/lib/plain-object'
import type { ToolHooks } from '@/tools/tool-hooks'
import { withAgentNote, withPostHogUrl } from '@/tools/tool-utils'
import type { Context } from '@/tools/types'

const ACTIVATION_PATH = '/inbox/activate'

// The activation page lives in the result rather than in guidance, so an agent learns it from the setup state it read.
async function afterResponse(context: Context, _params: unknown, result: unknown): Promise<unknown> {
    if (!isRecord(result) || result.completed_at !== null) {
        return result
    }
    const withUrl = await withPostHogUrl(context, result, ACTIVATION_PATH)
    const notes = [`Self-driving is not active in this project. The user can turn it on at ${withUrl._posthogUrl}.`]
    if (result.github_optional_available === true) {
        notes.push(
            `GitHub connects the data to code, so agents can find root causes and suggest changes. ` +
                `The user can also start without GitHub at ${withUrl._posthogUrl}/without-github, ` +
                `and Self-driving still surfaces issues and data correlations.`
        )
    }
    return withAgentNote(withUrl, notes.join(' '))
}

export default { afterResponse } satisfies ToolHooks<unknown>
