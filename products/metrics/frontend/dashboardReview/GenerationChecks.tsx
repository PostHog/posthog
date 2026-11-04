import { useValues } from 'kea'

import { LemonBanner, LemonTag } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { teamLogic } from 'scenes/teamLogic'

import { getMetricsDashboardTemplatesPictureRetrieveUrl } from 'products/metrics/frontend/generated/api'
import type {
    MetricsDashboardTemplateApi,
    MetricsDashboardTemplateRoundApi,
} from 'products/metrics/frontend/generated/api.schemas'

function RoundVerdict({ round }: { round: MetricsDashboardTemplateRoundApi }): JSX.Element | null {
    if (round.looks_good) {
        return <LemonTag type="success">Passed</LemonTag>
    }
    if (round.looks_good === null) {
        return null
    }
    const problems = (
        <ul className="list-disc pl-4">
            {round.problems.map((problem) => (
                <li key={problem}>{problem}</li>
            ))}
        </ul>
    )
    return (
        <Tooltip title={problems}>
            <LemonTag type={round.revised ? 'muted' : 'warning'}>
                {round.revised ? 'Revised' : `${round.problems.length} problems`}
            </LemonTag>
        </Tooltip>
    )
}

export function GenerationChecks({ template }: { template: MetricsDashboardTemplateApi }): JSX.Element | null {
    const { currentTeamId } = useValues(teamLogic)

    if (!template.rounds.length) {
        return null
    }
    const lastRound = template.rounds[template.rounds.length - 1]
    const openProblems = lastRound.looks_good === false && !lastRound.revised ? lastRound.problems : []

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap gap-2">
                {template.rounds.map((round) => {
                    const pictureUrl = getMetricsDashboardTemplatesPictureRetrieveUrl(
                        String(currentTeamId),
                        template.id,
                        { round: round.round }
                    )
                    return (
                        <div key={round.round} className="flex flex-col gap-1 w-48">
                            {round.has_picture && (
                                <Link to={pictureUrl} target="_blank">
                                    <img
                                        src={pictureUrl}
                                        alt={`AI check ${round.round}`}
                                        className="w-full h-28 object-cover object-top rounded border border-primary"
                                    />
                                </Link>
                            )}
                            <div className="flex items-center justify-between gap-1 text-xs">
                                <span className="text-secondary">AI check {round.round}</span>
                                <RoundVerdict round={round} />
                            </div>
                        </div>
                    )
                })}
            </div>
            {openProblems.length > 0 && (
                <LemonBanner type="warning">
                    <div className="font-semibold">The AI check found problems that it did not fix</div>
                    <ul className="list-disc pl-4">
                        {openProblems.map((problem) => (
                            <li key={problem}>{problem}</li>
                        ))}
                    </ul>
                </LemonBanner>
            )}
            {template.dropped_panels.length > 0 && (
                <p className="text-xs text-secondary mb-0">
                    Left out because the query failed: {template.dropped_panels.join(', ')}
                </p>
            )}
        </div>
    )
}
