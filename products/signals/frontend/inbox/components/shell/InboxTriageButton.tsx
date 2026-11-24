import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'
import { Button, Kbd } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { KeyboardShortcut } from 'lib/lemon-ui/KeyboardShortcut/KeyboardShortcut'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { reportListLogic, sectionListLogicProps } from '../../logics/reportListLogic'
import { INBOX_PRIMARY_REPORT_SECTION_KEY } from '../../types'

const TRIAGE_TOOLTIP = 'Go through the reports that need a pull request one at a time'
const NOTHING_TO_TRIAGE = 'No reports in this view need a pull request'
// pinned: autocapture selector. Triage usage insights filter clicks on this data-attr.
const TRIAGE_DATA_ATTR = 'inbox-triage-mode'

export function triageLabel(count: number | null, countIsCapped: boolean, compact: boolean): string {
    if (count === null) {
        return compact ? 'Triage' : 'Triage mode'
    }
    const shownCount = `${humanFriendlyNumber(count)}${countIsCapped ? '+' : ''}`
    if (compact) {
        return `Triage ${shownCount}`
    }
    return `Triage ${shownCount} ${count === 1 && !countIsCapped ? 'report' : 'reports'}`
}

/**
 * Opens triage mode from the scene header. It is an action, not a filter, so it sits apart from the
 * filter row. Triage walks the primary section with the Reports tab's filters and scope, so the
 * count comes from that same section and matches what triage will show.
 * `compact` drops the hotkey hint for the narrow tab row. The scene binds `t` either way.
 */
export function InboxTriageButton({ compact = false }: { compact?: boolean }): JSX.Element {
    const { count, countIsCapped } = useValues(reportListLogic(sectionListLogicProps(INBOX_PRIMARY_REPORT_SECTION_KEY)))
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    // Experiment: does a neutral button change how often people open triage mode?
    const neutralStyle = useFeatureFlag('INBOX_TRIAGE_BUTTON_COLOR', 'test')
    const disabledReason = count === 0 ? NOTHING_TO_TRIAGE : undefined
    const label = triageLabel(count, countIsCapped, compact)

    if (todayRailNav) {
        return (
            <Button
                variant={neutralStyle ? 'outline' : 'primary'}
                render={<LinkPrimitive to={urls.inboxTriage()} />}
                tooltip={TRIAGE_TOOLTIP}
                disabledReason={disabledReason}
                data-attr={TRIAGE_DATA_ATTR}
            >
                {label}
                {!compact && <Kbd>T</Kbd>}
            </Button>
        )
    }
    return (
        <LemonButton
            type={neutralStyle ? 'secondary' : 'primary'}
            size="small"
            to={urls.inboxTriage()}
            sideIcon={compact ? undefined : <KeyboardShortcut t />}
            tooltip={TRIAGE_TOOLTIP}
            disabledReason={disabledReason}
            data-attr={TRIAGE_DATA_ATTR}
        >
            {label}
        </LemonButton>
    )
}
