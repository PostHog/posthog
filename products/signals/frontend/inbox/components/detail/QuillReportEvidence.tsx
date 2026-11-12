import { useActions, useValues } from 'kea'

import { Button, Text } from '@posthog/quill'

import { todayReportLogic } from 'scenes/project-homepage/today/todayReportLogic'
import { TodayReportSignalRow } from 'scenes/project-homepage/today/TodayReportSignalRow'
import { TodaySectionTitle } from 'scenes/project-homepage/today/TodaySectionTitle'

export function QuillReportEvidence({ reportId }: { reportId: string }): JSX.Element | null {
    const logic = todayReportLogic({ reportId })
    const { shownEvidence, evidenceCount, allEvidence, allEvidenceLoading } = useValues(logic)
    const { loadAllEvidence } = useActions(logic)

    if (evidenceCount === 0) {
        return null
    }

    return (
        <section className="flex flex-col gap-0.5" aria-label="Evidence" data-attr="inbox-report-evidence">
            <div className="flex items-baseline justify-between gap-3">
                <TodaySectionTitle>Evidence</TodaySectionTitle>
                {!allEvidence && evidenceCount > shownEvidence.length && (
                    <Button
                        variant="link-muted"
                        size="sm"
                        className="-me-2"
                        loading={allEvidenceLoading}
                        onClick={() => loadAllEvidence()}
                        data-attr="inbox-report-evidence-all"
                    >
                        {`See all ${evidenceCount}`}
                    </Button>
                )}
            </div>
            {shownEvidence.length === 0 ? (
                <Text size="sm" variant="muted" render={<p className="m-0" />}>
                    No signals are attached to this report yet.
                </Text>
            ) : (
                <div className="-mx-2 flex flex-col">
                    {shownEvidence.map((signal) => (
                        <TodayReportSignalRow key={signal.signal_id} reportId={reportId} signal={signal} />
                    ))}
                </div>
            )}
        </section>
    )
}
