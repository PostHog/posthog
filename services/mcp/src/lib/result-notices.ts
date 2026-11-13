import { z } from 'zod'

export const RESULT_NOTICES_KEY = 'agent_notices'

const resultNoticeSchema = z.object({
    source: z.string().min(1),
    key: z.string().min(1),
    text: z.string().min(1),
})

export type ResultNotice = z.infer<typeof resultNoticeSchema>

// Notices never reach the agent as part of the result: guidance decides whether and when to show them.
export function takeResultNotices(result: unknown): { result: unknown; notices: ResultNotice[] } {
    if (typeof result !== 'object' || result === null || Array.isArray(result) || !(RESULT_NOTICES_KEY in result)) {
        return { result, notices: [] }
    }
    const { [RESULT_NOTICES_KEY]: raw, ...rest } = result as Record<string, unknown>
    const parsed = z.array(resultNoticeSchema).safeParse(raw)
    return { result: rest, notices: parsed.success ? parsed.data : [] }
}
