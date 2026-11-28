import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { ScoutHistoryTab, scoutDetailLogic } from '../../../logics/scoutDetailLogic'

const END_LABELS: Record<ScoutHistoryTab, string> = {
    runs: 'No older runs.',
    reports: 'No older reports.',
    signals: 'No older signals.',
}

/**
 * The control under a scout history tab that loads the next older page. Once a page comes back short
 * there is nothing older, so it says that instead.
 */
export function ScoutLoadOlderButton({ skillName, tab }: { skillName: string; tab: ScoutHistoryTab }): JSX.Element {
    const { olderRuns, olderRunsLoading, olderReports, olderReportsLoading, olderSignals, olderSignalsLoading } =
        useValues(scoutDetailLogic({ skillName }))
    const { loadOlder } = useActions(scoutDetailLogic({ skillName }))

    const [pages, loading] =
        tab === 'runs'
            ? [olderRuns, olderRunsLoading]
            : tab === 'reports'
              ? [olderReports, olderReportsLoading]
              : [olderSignals, olderSignalsLoading]

    if (pages.exhausted) {
        return <span className="text-[11px] text-muted">{END_LABELS[tab]}</span>
    }

    return (
        <LemonButton
            type="secondary"
            size="small"
            className="self-start"
            loading={loading}
            onClick={() => loadOlder(tab)}
            data-attr={`scout-detail-load-older-${tab}`}
        >
            Load older
        </LemonButton>
    )
}
