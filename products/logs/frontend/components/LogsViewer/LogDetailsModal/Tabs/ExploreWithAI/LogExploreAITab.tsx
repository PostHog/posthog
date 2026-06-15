import { useActions, useValues } from 'kea'
import { BindLogic } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { EmptyState } from './EmptyState'
import { ExplanationContent } from './ExplanationContent'
import { LoadingState } from './LoadingState'
import { LogExploreAILogicProps, logExploreAILogic } from './logExploreAILogic'

export interface LogExploreAITabProps {
    logUuid: string
    logTimestamp: string
    onApplyFilter?: (filterKey: string, filterValue: string, attributeType: 'log' | 'resource') => void
}

export function LogExploreAITab({ logUuid, logTimestamp, onApplyFilter }: LogExploreAITabProps): JSX.Element {
    const logicProps: LogExploreAILogicProps = { logUuid, logTimestamp }

    return (
        <BindLogic logic={logExploreAILogic} props={logicProps}>
            <LogExploreAITabContent onApplyFilter={onApplyFilter} />
        </BindLogic>
    )
}

function LogExploreAITabContent({
    onApplyFilter,
}: {
    onApplyFilter?: (filterKey: string, filterValue: string, attributeType: 'log' | 'resource') => void
}): JSX.Element {
    const { explanation, explanationLoading, explanationError, dataProcessingAccepted } = useValues(logExploreAILogic)
    const { loadExplanation } = useActions(logExploreAILogic)

    if (explanationLoading) {
        return <LoadingState />
    }

    if (explanationError) {
        return (
            <LemonBanner type="error" className="m-4">
                {explanationError}
            </LemonBanner>
        )
    }

    if (!explanation) {
        return (
            <EmptyState
                onGenerate={loadExplanation}
                dataProcessingAccepted={dataProcessingAccepted}
                loading={explanationLoading}
            />
        )
    }

    return <ExplanationContent explanation={explanation} onApplyFilter={onApplyFilter} />
}
