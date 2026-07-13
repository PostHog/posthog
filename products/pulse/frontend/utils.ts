import { getCurrentTeamId } from 'lib/utils/getAppContext'

/** First page only — deliberate for alpha; load-more is a follow-up. */
export const LIST_PAGE_SIZE = 100

export function currentProjectId(): string {
    return String(getCurrentTeamId())
}
