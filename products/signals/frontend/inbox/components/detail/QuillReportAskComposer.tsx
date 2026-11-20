import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { todayReportLogic } from 'scenes/project-homepage/today/todayReportLogic'

import { Composer } from 'products/posthog_ai/frontend/api/composer'

/** The question box that "Ask about it" opens. It stays closed until then, so the report leads the page. */
export function QuillReportAskComposer({ reportId }: { reportId: string }): JSX.Element | null {
    const logic = todayReportLogic({ reportId })
    const { askingAi, composerOpen, draft } = useValues(logic)
    const { askAboutReport, setDraft } = useActions(logic)
    const textAreaRef = useRef<HTMLTextAreaElement>(null)

    useEffect(() => {
        if (composerOpen) {
            textAreaRef.current?.focus({ preventScroll: true })
        }
    }, [composerOpen])

    if (!composerOpen) {
        return null
    }

    return (
        <Composer.Root
            value={draft}
            onChange={setDraft}
            onSubmit={() => askAboutReport(draft.trim(), 'detail_pane')}
            textAreaRef={textAreaRef}
            loading={askingAi}
            disabled={askingAi}
        >
            <Composer.Frame>
                <Composer.Field>
                    <Composer.Placeholder>Ask PostHog AI about this report</Composer.Placeholder>
                    <Composer.Textarea
                        maxRows={6}
                        className="[mask-image:linear-gradient(to_bottom,black_calc(100%-1rem),transparent)]"
                        data-attr="inbox-report-prompt-input"
                    />
                </Composer.Field>
            </Composer.Frame>
            <Composer.Submit data-attr="inbox-report-prompt-submit" />
        </Composer.Root>
    )
}
