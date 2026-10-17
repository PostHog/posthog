import { useValues } from 'kea'

import { LemonBanner, LemonTag } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { teamLogic } from 'scenes/teamLogic'

import { getMetricsDashboardTemplatesPictureRetrieveUrl } from 'products/metrics/frontend/generated/api'
import {
    DashboardTemplateStatusEnumApi,
    MetricsDashboardTemplateSourceEnumApi,
    type MetricsDashboardTemplateApi,
    type MetricsDashboardTemplateRoundApi,
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

    const lastRound = template.rounds.length ? template.rounds[template.rounds.length - 1] : null
    const openProblems = lastRound && lastRound.looks_good === false && !lastRound.revised ? lastRound.problems : []
    const uncheckedPictures =
        !lastRound &&
        template.source === MetricsDashboardTemplateSourceEnumApi.Generated &&
        template.status !== DashboardTemplateStatusEnumApi.Generating
    if (!lastRound && !uncheckedPictures && !template.dropped_panels.length) {
        return null
    }

    return (
        <div className="flex flex-col gap-2">
            {uncheckedPictures && (
                <LemonBanner type="info">
                    The AI did not check a picture of this dashboard. Look at every panel before you approve it.
                </LemonBanner>
            )}
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
                <div className="text-xs text-secondary">
                    <div>Left out because the query failed or showed no data:</div>
                    <ul className="list-disc pl-4 mb-0">
                        {template.dropped_panels.map((panel) => (
                            <li key={panel}>{panel}</li>
                        ))}
                    </ul>
                </div>
            )}
        </div>
    )
}
