import { useActions, useValues } from 'kea'

import { IconEllipsis, IconPencil } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonMenu, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { Query } from '~/queries/Query/Query'

import { JourneyStepsFlow } from '../../components/JourneyStepsFlow'
import { UserJourneyLogicProps, userJourneyLogic } from '../../userJourneyLogic'

export const scene: SceneExport<UserJourneyLogicProps> = {
    component: UserJourneyScene,
    logic: userJourneyLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

export function UserJourneyScene({ id }: UserJourneyLogicProps): JSX.Element {
    const userJourneysEnabled = useFeatureFlag('USER_JOURNEYS')
    const logic = userJourneyLogic({ id })
    const {
        journey,
        journeyLoading,
        journeyLoadError,
        insightQuery,
        funnelQueryLoading,
        funnelQueryLoadFailed,
        deleting,
    } = useValues(logic)
    const { loadJourney, loadFunnelQuery, deleteJourney, setInsightQuery } = useActions(logic)

    if (!userJourneysEnabled || journeyLoadError === 'not_found') {
        return <NotFound object={userJourneysEnabled ? 'journey' : 'page'} />
    }

    if (journeyLoadError === 'error') {
        return (
            <SceneContent>
                <SceneTitleSection name="Journey" resourceType={{ type: 'insight/paths' }} />
                <LemonBanner
                    type="error"
                    action={{ children: 'Try again', onClick: loadJourney, 'data-attr': 'user-journey-retry' }}
                >
                    Couldn't load this journey. Check your connection and try again.
                </LemonBanner>
            </SceneContent>
        )
    }

    const confirmDelete = (): void => {
        LemonDialog.open({
            title: `Delete ${journey?.name ?? 'this journey'}?`,
            description: 'The journey and its steps are deleted. This cannot be undone.',
            primaryButton: {
                children: 'Delete',
                status: 'danger',
                onClick: deleteJourney,
                'data-attr': 'user-journey-delete-confirm',
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={journey?.name}
                description={journey?.description || null}
                isLoading={journeyLoading && !journey}
                resourceType={{ type: 'insight/paths' }}
                actions={
                    <>
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconPencil />}
                            to={urls.userJourneyEdit(id)}
                            disabledReason={!journey ? 'Loading the journey' : undefined}
                            data-attr="user-journey-edit"
                        >
                            Edit
                        </LemonButton>
                        <LemonMenu
                            items={[
                                {
                                    label: 'Delete journey',
                                    status: 'danger',
                                    onClick: confirmDelete,
                                    disabledReason: deleting ? 'Deleting the journey' : undefined,
                                    'data-attr': 'user-journey-delete',
                                },
                            ]}
                        >
                            <LemonButton
                                size="small"
                                icon={<IconEllipsis />}
                                aria-label="More actions"
                                disabledReason={!journey ? 'Loading the journey' : undefined}
                                data-attr="user-journey-more"
                            />
                        </LemonMenu>
                    </>
                }
            />

            {journey ? (
                <div className="flex items-center gap-x-4 gap-y-1 flex-wrap text-secondary text-xs">
                    <LemonTag type={journey.source === 'toolbar' ? 'highlight' : 'default'}>
                        {journey.source === 'toolbar' ? 'From toolbar' : 'Manual'}
                    </LemonTag>
                    <span>
                        <span translate="no">{journey.conversion_window_minutes}</span>
                        <span>-minute conversion window</span>
                    </span>
                    <span className="flex items-center gap-1">
                        <span>Created</span>
                        <TZLabel time={journey.created_at} />
                    </span>
                    <span className="flex items-center gap-1">
                        <span>Updated</span>
                        <TZLabel time={journey.updated_at} />
                    </span>
                </div>
            ) : null}

            <SceneDivider />

            <div className="grid grid-cols-1 @min-[64rem]/main-content:grid-cols-[minmax(16rem,1fr)_2fr] gap-6">
                <SceneSection title="Steps" isLoading={journeyLoading && !journey}>
                    {journey ? <JourneyStepsFlow steps={journey.steps} /> : <LemonSkeleton className="h-40" />}
                </SceneSection>

                <SceneSection
                    title="Conversion"
                    description="Sessions that completed each step in order, within the conversion window."
                >
                    {funnelQueryLoadFailed ? (
                        <LemonBanner
                            type="error"
                            action={{
                                children: 'Try again',
                                onClick: loadFunnelQuery,
                                'data-attr': 'user-journey-funnel-retry',
                            }}
                        >
                            Couldn't load the conversion funnel for this journey.
                        </LemonBanner>
                    ) : insightQuery ? (
                        <Query query={insightQuery} setQuery={setInsightQuery} readOnly />
                    ) : funnelQueryLoading ? (
                        <LemonSkeleton className="h-80" />
                    ) : null}
                </SceneSection>
            </div>

            <SceneDivider />

            <SceneSection
                title="Deploy comparisons"
                description="Conversion for each step before and after each deploy, to catch regressions."
            >
                <div className="border border-dashed rounded p-6 text-center text-secondary">
                    Deploy comparisons aren't available yet. Once they are, each journey shows them here.
                </div>
            </SceneSection>
        </SceneContent>
    )
}
