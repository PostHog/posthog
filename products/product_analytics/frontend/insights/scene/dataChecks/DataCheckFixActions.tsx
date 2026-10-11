import { useActions } from 'kea'

import { IconCopy, IconSparkles } from '@posthog/icons'
import { Button } from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import type { DataCheck } from './dataChecks'
import { insightDataChecksLogic } from './insightDataChecksLogic'

export function DataCheckFixActions({
    insightProps,
    check,
}: {
    insightProps: InsightLogicProps
    check: DataCheck
}): JSX.Element {
    const { sendFixPrompt } = useActions(insightDataChecksLogic(insightProps))

    return (
        <div className="flex flex-wrap items-center gap-2">
            <Button
                variant="outline"
                size="sm"
                onClick={() => sendFixPrompt(check, 'posthog_ai')}
                data-attr="quill-insight-data-check-fix-with-posthog-ai"
            >
                <IconSparkles />
                Fix with PostHog AI
            </Button>
            <Button
                variant="outline"
                size="sm"
                onClick={() => sendFixPrompt(check, 'clipboard')}
                data-attr="quill-insight-data-check-copy-prompt"
            >
                <IconCopy />
                Copy prompt
            </Button>
        </div>
    )
}
