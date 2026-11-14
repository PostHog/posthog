import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { todayReportLogic } from 'scenes/project-homepage/today/todayReportLogic'

/** Opens the question box for PostHog AI. It sits beside the primary action, as on the Home report. */
export function QuillReportAskButton({ reportId }: { reportId: string }): JSX.Element {
    const logic = todayReportLogic({ reportId })
    const { composerOpen } = useValues(logic)
    const { openComposer } = useActions(logic)

    return (
        <Button onClick={() => openComposer()} aria-expanded={composerOpen} data-attr="inbox-report-ask">
            <IconSparkles />
            Ask about it
        </Button>
    )
}
