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

function triageLabel(count: number | null): string {
    if (count === null) {
        return 'Triage mode'
    }
    return `Triage ${humanFriendlyNumber(count)} ${count === 1 ? 'report' : 'reports'}`
}

/**
 * Opens triage mode from the scene header. It is an action, not a filter, so it sits apart from the
 * filter row. Triage walks the primary section with the Reports tab's filters and scope, so the
 * count comes from that same section and matches what triage will show.
 */
export function InboxTriageButton(): JSX.Element {
    const { count } = useValues(reportListLogic(sectionListLogicProps(INBOX_PRIMARY_REPORT_SECTION_KEY)))
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const disabledReason = count === 0 ? NOTHING_TO_TRIAGE : undefined
    const label = triageLabel(count)

    if (todayRailNav) {
        return (
            <Button
                variant="primary"
                render={<LinkPrimitive to={urls.inboxTriage()} />}
                tooltip={TRIAGE_TOOLTIP}
                disabledReason={disabledReason}
                data-attr={TRIAGE_DATA_ATTR}
            >
                {label}
                <Kbd>T</Kbd>
            </Button>
        )
    }
    return (
        <LemonButton
            type="primary"
            size="small"
            to={urls.inboxTriage()}
            sideIcon={<KeyboardShortcut t />}
            tooltip={TRIAGE_TOOLTIP}
            disabledReason={disabledReason}
            data-attr={TRIAGE_DATA_ATTR}
        >
            {label}
        </LemonButton>
    )
}
