import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTable, Link } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { CriteriaSummary, describeEvidenceProgress, OutcomeEvidence } from './criteriaUtils'
import type { OutcomeLatchApi } from './generated/api.schemas'
import { OutcomeLogicProps, outcomeLogic } from './outcomeLogic'

export const scene: SceneExport<OutcomeLogicProps> = {
    component: OutcomeScene,
    logic: outcomeLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

export function OutcomeScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { outcome, outcomeLoading, reached, reachedLoading } = useValues(outcomeLogic)
    const { recalculate, refresh } = useActions(outcomeLogic)

    if (!featureFlags[FEATURE_FLAGS.OUTCOMES]) {
        return <NotFound object="page" />
    }

    if (outcomeLoading && !outcome) {
        return <LemonSkeleton active />
    }

    if (!outcome) {
        return <NotFound object="outcome" />
    }

    const columns = [
        {
            title: 'Person',
            render: function Render(_: any, latch: OutcomeLatchApi) {
                return (
                    <Link to={urls.personByDistinctId(latch.distinct_id)} data-attr="outcome-reached-person">
                        {latch.distinct_id}
                    </Link>
                )
            },
        },
        {
            title: 'Reached at',
            render: function Render(_: any, latch: OutcomeLatchApi) {
                return <TZLabel time={latch.reached_at} />
            },
        },
        {
            title: 'Progress when reached',
            render: function Render(_: any, latch: OutcomeLatchApi) {
                return <span>{describeEvidenceProgress(latch.evidence as unknown as OutcomeEvidence)}</span>
            },
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name={outcome.name}
                description={outcome.description || undefined}
                resourceType={{ type: 'metrics' }}
                actions={
                    <>
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconRefresh />}
                            onClick={() => refresh()}
                            data-attr="outcome-refresh"
                        >
                            Refresh
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={() => recalculate()}
                            data-attr="outcome-recalculate"
                        >
                            Recalculate now
                        </LemonButton>
                    </>
                }
            />
            <div className="flex flex-wrap gap-8 border rounded p-4 bg-surface-primary">
                <div>
                    <div className="text-muted text-xs uppercase">Criteria</div>
                    <CriteriaSummary criteria={outcome.criteria} />
                </div>
                <div>
                    <div className="text-muted text-xs uppercase">Reached by</div>
                    <div className="text-lg">{outcome.reached_count} persons</div>
                </div>
                <div>
                    <div className="text-muted text-xs uppercase">Last calculated</div>
                    <div className="text-lg">
                        {outcome.last_calculated_at ? <TZLabel time={outcome.last_calculated_at} /> : 'Not yet'}
                    </div>
                </div>
            </div>
            <LemonTable
                data-attr="outcome-reached-table"
                rowKey="id"
                dataSource={reached}
                columns={columns}
                loading={reachedLoading}
                emptyState="No one has reached this outcome yet. New facts appear after each calculation run."
            />
        </SceneContent>
    )
}
