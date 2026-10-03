import { z } from 'zod'

import { env } from '@/lib/env'
import type { Context, ToolBase } from '@/tools/types'

// Club Hoguin is a separate service (products/games/services/club-hoguin). This tool only hands out
// its address, so an agent can open the town for the person without knowing where it is hosted.
const schema = z.object({})

type Params = z.infer<typeof schema>

export interface ClubHoguinOpenResult {
    /** The town in the browser. Open this for the person, or show it as a link. */
    url: string
    /** The same town, laid out for an iframe. */
    embedUrl: string
    /** How to open the town inside Claude Code instead of a browser. */
    claudeCode: string
}

export const clubHoguinOpenHandler: ToolBase<typeof schema, ClubHoguinOpenResult>['handler'] = async (
    _context: Context,
    _params: Params
): Promise<ClubHoguinOpenResult> => {
    const configured = env.CLUB_HOGUIN_URL?.trim()
    if (!configured) {
        throw new Error('Club Hoguin is not set up on this PostHog server: CLUB_HOGUIN_URL is not configured.')
    }
    const base = configured.replace(/\/+$/, '')
    return {
        url: `${base}/`,
        embedUrl: `${base}/?embed=1`,
        claudeCode:
            'With the Club Hoguin plugin loaded, run /hoguin to open the town in a pane, or /hoguin web to open it in the browser.',
    }
}

export default (): ToolBase<typeof schema, ClubHoguinOpenResult> => ({
    name: 'club-hoguin-open',
    schema,
    handler: clubHoguinOpenHandler,
})
