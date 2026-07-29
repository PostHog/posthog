import { z } from 'zod'

import type { Context, ToolBase } from '@/tools/types'

import { generateAppUrlHandler } from './generate-app-url'

const schema = z.object({
    url: z
        .string()
        .describe(
            'Where to take the user: a full PostHog URL copied verbatim from a tool result (`_posthogUrl`) or ' +
                'from generate-app-url output, or a path template from the generate-app-url catalog (then fill `params`).'
        ),
    params: z
        .record(z.string(), z.string())
        .default({})
        .describe('Values for the `{placeholders}` when `url` is a path template; pass {} otherwise.'),
})

type Params = z.infer<typeof schema>

interface NavigateResult {
    /** Resolved destination. The tab where the user is viewing this chat follows it automatically; also share it as a link. */
    url: string
}

export const navigateUserHandler: ToolBase<typeof schema, NavigateResult>['handler'] = async (
    context: Context,
    params: Params
): Promise<NavigateResult> => {
    // A leading slash means a catalog path template — resolve it exactly like generate-app-url,
    // catalog validation included.
    if (params.url.startsWith('/')) {
        return await generateAppUrlHandler(context, { url: params.url, params: params.params })
    }

    const projectId = await context.stateManager.getProjectId()
    const origin = new URL(context.api.getProjectBaseUrl(projectId)).origin
    let parsed: URL
    try {
        parsed = new URL(params.url)
    } catch {
        throw new Error(
            `"${params.url}" is not a valid URL — pass a _posthogUrl from a tool result verbatim, or a path template from the generate-app-url catalog.`
        )
    }
    if (parsed.origin !== origin) {
        throw new Error(
            `Can only navigate within this PostHog instance (${origin}) — pass a _posthogUrl from a tool result, or a path template from the generate-app-url catalog.`
        )
    }
    return { url: parsed.toString() }
}

export default (): ToolBase<typeof schema, NavigateResult> => ({
    name: 'navigate-user',
    schema,
    handler: navigateUserHandler,
})
