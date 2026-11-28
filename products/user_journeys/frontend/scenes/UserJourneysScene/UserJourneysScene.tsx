import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconEllipsis, IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonMenu, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { TZLabel } from 'lib/components/TZLabel'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import type { JourneyApi } from '../../generated/api.schemas'
import { userJourneysLogic } from '../../userJourneysLogic'

export const scene: SceneExport = {
    component: UserJourneysScene,
    logic: userJourneysLogic,
}

const DESCRIPTION = 'Save the paths people take through your product and see how many sessions complete them.'

export function UserJourneysScene(): JSX.Element {
    const userJourneysEnabled = useFeatureFlag('USER_JOURNEYS')
    const { journeys, journeysLoading, journeysLoadFailed, deletingJourneyIds } = useValues(userJourneysLogic)
    const { loadJourneys, deleteJourney } = useActions(userJourneysLogic)

    if (!userJourneysEnabled) {
        return <NotFound object="page" />
    }

    const confirmDelete = (journey: JourneyApi): void => {
        LemonDialog.open({
            title: `Delete ${journey.name}?`,
            description: 'The journey and its steps are deleted. This cannot be undone.',
            primaryButton: {
                children: 'Delete',
                status: 'danger',
                onClick: () => deleteJourney(journey),
                'data-attr': 'user-journey-delete-confirm',
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    const isEmpty = journeys !== null && journeys.length === 0

    return (
        <SceneContent>
            <SceneTitleSection
                name="User journeys"
                description={DESCRIPTION}
                resourceType={{ type: 'insight/paths' }}
                actions={
                    isEmpty ? undefined : (
                        <LemonButton
                            type="primary"
                            size="small"
                            icon={<IconPlus />}
                            to={urls.userJourneyNew()}
                            data-attr="user-journeys-new"
                        >
                            New journey
                        </LemonButton>
                    )
                }
            />

            {journeysLoadFailed && journeys === null ? (
                <LemonBanner
                    type="error"
                    action={{ children: 'Try again', onClick: loadJourneys, 'data-attr': 'user-journeys-retry' }}
                >
                    Couldn't load your journeys. Check your connection and try again.
                </LemonBanner>
            ) : isEmpty ? (
                <ProductIntroduction
                    thingName="journey"
                    description="A journey is a path through your product that you want people to complete, like signing up from the pricing page. Add its steps as pageviews and clicks, in order, and PostHog counts how many sessions finish it."
                    action={() => router.actions.push(urls.userJourneyNew())}
                    hogLayout="responsive"
                    useMainContentContainerQueries
                />
            ) : (
                <LemonTable
                    dataSource={journeys ?? []}
                    loading={journeysLoading && journeys === null}
                    rowKey="id"
                    pagination={{ pageSize: 50 }}
                    nouns={['journey', 'journeys']}
                    data-attr="user-journeys-table"
                    columns={[
                        {
                            title: 'Name',
                            key: 'name',
                            render: (_, journey) => (
                                <LemonTableLink
                                    to={urls.userJourney(journey.id)}
                                    title={journey.name}
                                    description={journey.description || undefined}
                                />
                            ),
                            sorter: (a, b) => a.name.localeCompare(b.name),
                        },
                        {
                            title: 'Steps',
                            key: 'steps',
                            align: 'right',
                            render: (_, journey) => <span translate="no">{journey.steps.length}</span>,
                            sorter: (a, b) => a.steps.length - b.steps.length,
                        },
                        {
                            title: 'Source',
                            key: 'source',
                            render: (_, journey) => (
                                <LemonTag type={journey.source === 'toolbar' ? 'highlight' : 'default'}>
                                    {journey.source === 'toolbar' ? 'Toolbar' : 'Manual'}
                                </LemonTag>
                            ),
                        },
                        {
                            title: 'Created',
                            key: 'created_at',
                            render: (_, journey) => <TZLabel time={journey.created_at} />,
                            sorter: (a, b) => a.created_at.localeCompare(b.created_at),
                        },
                        {
                            title: 'Updated',
                            key: 'updated_at',
                            render: (_, journey) => <TZLabel time={journey.updated_at} />,
                            sorter: (a, b) => a.updated_at.localeCompare(b.updated_at),
                        },
                        {
                            key: 'actions',
                            width: 0,
                            render: (_, journey) => (
                                <LemonMenu
                                    items={[
                                        {
                                            label: 'Edit',
                                            to: urls.userJourneyEdit(journey.id),
                                            'data-attr': 'user-journeys-row-edit',
                                        },
                                        {
                                            items: [
                                                {
                                                    label: 'Delete',
                                                    status: 'danger',
                                                    onClick: () => confirmDelete(journey),
                                                    disabledReason: deletingJourneyIds[journey.id]
                                                        ? 'Deleting the journey'
                                                        : undefined,
                                                    'data-attr': 'user-journeys-row-delete',
                                                },
                                            ],
                                        },
                                    ]}
                                >
                                    <LemonButton
                                        size="small"
                                        icon={<IconEllipsis />}
                                        aria-label={`More actions for ${journey.name}`}
                                        data-attr="user-journeys-row-more"
                                    />
                                </LemonMenu>
                            ),
                        },
                    ]}
                />
            )}
        </SceneContent>
    )
}
