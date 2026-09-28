import { useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { CandidateMetricSection } from './sections/CandidateMetricSection'
import { IdentitySummarySection } from './sections/IdentitySummarySection'
import { PreviousExperimentsSection } from './sections/PreviousExperimentsSection'
import { SdkProfileSection } from './sections/SdkProfileSection'
import { SharedMetricsSection } from './sections/SharedMetricsSection'
import { TargetSurfaceSection } from './sections/TargetSurfaceSection'
import { TeamDefaultsSection } from './sections/TeamDefaultsSection'
import { setupInspectorLogic } from './setupInspectorLogic'

export function SetupInspectorResults(): JSX.Element {
    const { setupContext, setupContextLoading, setupContextError, identitySummary } = useValues(setupInspectorLogic)

    if (setupContextLoading && !setupContext) {
        return (
            <div className="flex flex-col gap-2">
                <LemonSkeleton className="h-8 w-1/3" />
                <LemonSkeleton repeat={6} className="h-6" />
            </div>
        )
    }
    if (setupContextError) {
        return <LemonBanner type="error">{setupContextError}</LemonBanner>
    }
    if (!setupContext) {
        return <p className="text-secondary mb-0">Read the setup context to see what an agent sees.</p>
    }
    return (
        <div className="flex flex-col gap-6">
            {identitySummary && <IdentitySummarySection facts={identitySummary} />}
            <TeamDefaultsSection section={setupContext.team_defaults} />
            <SdkProfileSection section={setupContext.sdk_profile} />
            <TargetSurfaceSection section={setupContext.target_surface} />
            <CandidateMetricSection section={setupContext.candidate_metric} />
            <PreviousExperimentsSection section={setupContext.previous_experiments} />
            <SharedMetricsSection section={setupContext.shared_metrics} />
        </div>
    )
}
