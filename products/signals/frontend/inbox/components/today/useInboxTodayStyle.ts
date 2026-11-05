import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

/** The Home report API answers only people with the new navigation, so the Home-style inbox needs both flags. */
export function useInboxTodayStyle(): boolean {
    const inboxTodayStyle = useFeatureFlag('INBOX_TODAY_STYLE')
    const railNav = useFeatureFlag('TODAY_RAIL_NAV')
    return inboxTodayStyle && railNav
}
