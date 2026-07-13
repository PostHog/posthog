import { useValues } from 'kea'

import { LemonCard, LemonTable, LemonTableColumns, Link, Tooltip } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import type { RunObservationApi } from '../generated/api.schemas'
import { visionActionRunSceneLogic } from './visionActionRunSceneLogic'
import { RunStatusTag } from './visionActionRunStatus'

export const scene: SceneExport = {
    component: VisionActionRunScene,
    logic: visionActionRunSceneLogic,
    productKey: ProductKey.REPLAY_VISION,
}

function RecordingsIncluded({ observations }: { observations: readonly RunObservationApi[] }): JSX.Element {
    const columns: LemonTableColumns<RunObservationApi> = [
        {
            // Matches the `[N]` citations in the summary above, so a reader can trace a cited theme to its row.
            title: '#',
            key: 'index',
            render: (_, obs) => <span className="text-muted whitespace-nowrap">[{obs.index}]</span>,
        },
        {
            title: 'Observation',
            key: 'observation',
            render: (_, obs) => (
                <Link
                    className="font-semibold truncate max-w-md inline-block align-bottom"
                    to={urls.replayVisionObservation(obs.id)}
                    title={obs.title || obs.session_id}
                >
                    {obs.title || obs.session_id}
                </Link>
            ),
        },
        {
            title: 'Person',
            key: 'person',
            // Plain text, not a link: the observation carries no reliable person distinct id (only the
            // subject email), so a person-page link would land on "person not found" whenever the id differs.
            render: (_, obs) =>
                obs.recording_subject_email ? (
                    <span className="truncate max-w-xs inline-block align-bottom" title={obs.recording_subject_email}>
                        {obs.recording_subject_email}
                    </span>
                ) : (
                    <Tooltip title="No person is associated with this recording">
                        <span className="text-muted">No person</span>
                    </Tooltip>
                ),
        },
        {
            title: 'Time',
            key: 'time',
            render: (_, obs) => <TZLabel time={obs.created_at} formatDate="MMM D, YYYY" formatTime="HH:mm" />,
        },
    ]

    return (
        <div className="flex flex-col gap-2">
            <h3 className="m-0">Recordings included: {observations.length}</h3>
            <LemonTable columns={columns} dataSource={[...observations]} rowKey="id" />
        </div>
    )
}

function VisionActionRunScene(): JSX.Element {
    const { run, runLoading, summaryMarkdown } = useValues(visionActionRunSceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    if (!featureFlags[FEATURE_FLAGS.REPLAY_VISION] || !featureFlags[FEATURE_FLAGS.REPLAY_VISION_ACTIONS]) {
        return <NotFound object="page" />
    }

    if (runLoading) {
        return (
            <SceneContent>
                <div className="flex justify-center p-8">
                    <Spinner className="text-2xl" />
                </div>
            </SceneContent>
        )
    }

    if (!run) {
        return (
            <SceneContent>
                <SceneTitleSection name="Run not found" resourceType={{ type: 'replay_vision' }} />
            </SceneContent>
        )
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Run summary"
                resourceType={{ type: 'replay_vision' }}
                actions={
                    <div className="flex items-center gap-2 text-sm text-secondary">
                        <RunStatusTag status={run.status} />
                        <TZLabel
                            time={run.scheduled_at ?? run.created_at}
                            formatDate="MMM D, YYYY"
                            formatTime="HH:mm"
                        />
                    </div>
                }
            />

            {run.synthesized_markdown ? (
                <LemonCard hoverEffect={false} className="p-4">
                    {/* Same untrusted-content guard as the scanner-page digest card. */}
                    <LemonMarkdown className="text-base" disableImages>
                        {summaryMarkdown}
                    </LemonMarkdown>
                </LemonCard>
            ) : run.status === 'running' ? (
                <div className="text-muted italic">This run is in progress — check back shortly for the summary.</div>
            ) : (
                <LemonBanner type={run.status === 'failed' ? 'error' : 'info'}>
                    <div className="font-semibold">
                        {run.status === 'failed'
                            ? 'This run failed'
                            : run.status === 'skipped'
                              ? 'This run was skipped'
                              : 'This run produced no summary'}
                    </div>
                    <div>{run.error_reason || 'No summary was produced for this run.'}</div>
                </LemonBanner>
            )}

            {run.observations.length > 0 ? (
                <RecordingsIncluded observations={run.observations} />
            ) : (
                run.synthesized_markdown && (
                    <div className="text-muted text-sm">
                        No recordings to show — they may predate this feature, or have since been deleted.
                    </div>
                )
            )}
        </SceneContent>
    )
}
