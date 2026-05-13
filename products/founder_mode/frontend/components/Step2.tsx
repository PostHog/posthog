import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { founderLogic } from '../scenes/founderLogic'
import { founderValidationLogic } from './founderValidationLogic'
import { ValidationReportView } from './ValidationReportView'

export function Step2(): JSX.Element {
    const { currentProjectId } = useValues(founderLogic)

    if (!currentProjectId) {
        return (
            <LemonBanner type="info">
                Complete stage 1 first. The validation step reads from the ideation payload of your founder project.
            </LemonBanner>
        )
    }

    return <Step2Inner projectId={currentProjectId} />
}

function Step2Inner({ projectId }: { projectId: string }): JSX.Element {
    const logic = founderValidationLogic({ projectId })
    const { projectLoading, report, ideation, status, errorMessage, isRunning } = useValues(logic)
    const { regenerate } = useActions(logic)

    if (projectLoading && !report) {
        return (
            <div className="flex flex-col gap-3">
                <LemonSkeleton className="h-8 w-1/3" />
                <LemonSkeleton className="h-32 w-full" />
                <LemonSkeleton className="h-32 w-full" />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-4">
            <header className="flex items-baseline justify-between gap-3">
                <div>
                    <h2 className="text-xl font-semibold">Validation</h2>
                    <p className="text-sm text-text-secondary mt-1">
                        Pressure-test the riskiest assumptions in your idea before you spend time building.
                    </p>
                </div>
                <LemonButton
                    icon={<IconRefresh />}
                    onClick={() => regenerate()}
                    disabledReason={isRunning ? 'Validation already running' : undefined}
                    type="secondary"
                    size="small"
                >
                    {report ? 'Re-run' : 'Run validation'}
                </LemonButton>
            </header>

            {status === 'failed' && (
                <LemonBanner type="error" action={{ children: 'Retry', onClick: () => regenerate() }}>
                    Validation failed: {errorMessage || 'unknown error'}
                </LemonBanner>
            )}

            {isRunning && (
                <LemonBanner type="info">
                    Researching competitors and synthesizing the report. This usually takes 20-60 seconds.
                </LemonBanner>
            )}

            {!report && !isRunning && status !== 'failed' && (
                <LemonBanner type="info">
                    No validation report yet. Hit "Run validation" to kick off a competitor + assumptions analysis.
                    {!ideation && <> Make sure stage 1 (ideation) is filled in first.</>}
                </LemonBanner>
            )}

            {report && <ValidationReportView report={report} />}
        </div>
    )
}
