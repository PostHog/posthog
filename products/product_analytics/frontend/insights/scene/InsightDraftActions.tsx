import { useActions, useValues } from 'kea'

import { Button, Text } from '@posthog/quill'

import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import type { InsightLogicProps } from '~/types'

export function InsightDraftActions({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element | null {
    const {
        insightChanged,
        insightSaving,
        canEditInsight,
        hasOverrides,
        hasDashboardItemId: isSaved,
    } = useValues(insightLogic(insightProps))
    const { saveInsight, saveAs } = useActions(insightLogic(insightProps))
    const { queryChanged } = useValues(insightDataLogic(insightProps))
    const { cancelChanges } = useActions(insightDataLogic(insightProps))

    if (isSaved && !insightChanged && !queryChanged) {
        return null
    }

    return (
        <div className="flex flex-wrap items-center gap-2">
            {isSaved && (
                <>
                    <Text size="sm" variant="muted" render={<span />}>
                        Unsaved changes
                    </Text>
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => cancelChanges()}
                        data-attr="quill-insight-discard"
                    >
                        Discard
                    </Button>
                </>
            )}
            {isSaved && (!canEditInsight || hasOverrides) ? (
                <Button variant="primary" size="sm" onClick={() => saveAs()} data-attr="quill-insight-save-as-new">
                    Save as new
                </Button>
            ) : (
                <Button
                    variant="primary"
                    size="sm"
                    loading={insightSaving}
                    onClick={() => saveInsight(true)}
                    data-attr="quill-insight-save"
                >
                    Save
                </Button>
            )}
        </div>
    )
}
