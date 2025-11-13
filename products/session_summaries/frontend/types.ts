import { UserBasicType } from '~/types'

export type SessionGroupSummaryListItemType = {
    id: string
    title: string
    session_count: number
    created_at: string
    created_by: UserBasicType | null
}

export type SessionGroupSummaryType = SessionGroupSummaryListItemType & {
    session_ids: string[]
    summary: Record<string, any>
    extra_summary_context: Record<string, any> | null
    extra_input_context: Record<string, any> | null
    run_metadata: Record<string, any> | null
    team: number
}
