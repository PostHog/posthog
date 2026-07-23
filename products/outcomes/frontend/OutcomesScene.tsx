import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonTable, LemonTableColumn, LemonTextArea } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { createdAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import type { OutcomeDefinitionApi } from './generated/api.schemas'
import { outcomesLogic } from './outcomesLogic'

export const scene: SceneExport = {
    component: OutcomesScene,
    logic: outcomesLogic,
    productKey: ProductKey.OUTCOMES,
}

export function OutcomesScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { outcomes, outcomesLoading, isNewOutcomeModalOpen } = useValues(outcomesLogic)
    const { openNewOutcomeModal, deleteOutcome } = useActions(outcomesLogic)

    if (!featureFlags[FEATURE_FLAGS.OUTCOMES]) {
        return <NotFound object="page" />
    }

    const shouldShowEmptyState = outcomes.length === 0 && !outcomesLoading

    const columns = [
        {
            title: 'Name',
            sticky: true,
            width: '30%',
            render: function Render(_: any, outcome: OutcomeDefinitionApi) {
                return (
                    <LemonTableLink
                        to={urls.outcome(outcome.id)}
                        title={outcome.name}
                        description={outcome.description}
                    />
                )
            },
        },
        {
            title: 'Condition',
            render: function Render(_: any, outcome: OutcomeDefinitionApi) {
                return (
                    <span>
                        <PropertyKeyInfo value={outcome.target_event} type={TaxonomicFilterGroupType.Events} /> &ge;{' '}
                        {outcome.threshold}
                    </span>
                )
            },
        },
        {
            title: 'Reached by',
            render: function Render(_: any, outcome: OutcomeDefinitionApi) {
                return <span>{outcome.reached_count} persons</span>
            },
        },
        {
            title: 'Last calculated',
            render: function Render(_: any, outcome: OutcomeDefinitionApi) {
                return outcome.last_calculated_at ? <TZLabel time={outcome.last_calculated_at} /> : <span>Not yet</span>
            },
        },
        {
            title: 'Created by',
            render: function Render(_: any, outcome: OutcomeDefinitionApi) {
                return <span>{outcome.created_by?.first_name || outcome.created_by?.email || '—'}</span>
            },
        },
        createdAtColumn<OutcomeDefinitionApi>() as LemonTableColumn<
            OutcomeDefinitionApi,
            keyof OutcomeDefinitionApi | undefined
        >,
        {
            width: 0,
            render: function Render(_: any, outcome: OutcomeDefinitionApi) {
                return (
                    <More
                        overlay={
                            <LemonMenuOverlay
                                items={[
                                    {
                                        label: 'Delete',
                                        status: 'danger',
                                        onClick: () => deleteOutcome(outcome.id),
                                    },
                                ]}
                            />
                        }
                    />
                )
            },
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name="Outcomes"
                description="Conditions over events that, once met by a person, become permanent facts and emit a $outcome_reached event."
                resourceType={{ type: 'metrics' }}
                actions={
                    <LemonButton
                        type="primary"
                        icon={<IconPlus />}
                        size="small"
                        data-attr="new-outcome-button"
                        onClick={() => openNewOutcomeModal()}
                    >
                        New outcome
                    </LemonButton>
                }
            />
            {shouldShowEmptyState ? (
                <ProductIntroduction
                    productName="Outcomes"
                    thingName="outcome"
                    description="Define what reaching success means — like activation or a PQL threshold — and PostHog will permanently record when each person gets there, emitting a $outcome_reached event you can chart or automate on."
                    isEmpty={shouldShowEmptyState}
                    action={() => openNewOutcomeModal()}
                />
            ) : (
                <LemonTable
                    data-attr="outcomes-table"
                    rowKey="id"
                    dataSource={outcomes}
                    columns={columns as LemonTableColumn<OutcomeDefinitionApi, any>[]}
                    loading={outcomesLoading}
                />
            )}
            <NewOutcomeModal isOpen={isNewOutcomeModalOpen} />
        </SceneContent>
    )
}

function NewOutcomeModal({ isOpen }: { isOpen: boolean }): JSX.Element {
    const { isNewOutcomeSubmitting, newOutcome } = useValues(outcomesLogic)
    const { closeNewOutcomeModal, submitNewOutcome, setNewOutcomeValue } = useActions(outcomesLogic)

    return (
        <LemonModal
            title="New outcome"
            description="A person reaches the outcome once they have performed the target event at least the threshold number of times."
            isOpen={isOpen}
            onClose={() => closeNewOutcomeModal()}
            footer={
                <>
                    <LemonButton type="secondary" onClick={() => closeNewOutcomeModal()}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        data-attr="create-outcome-submit"
                        loading={isNewOutcomeSubmitting}
                        disabledReason={isNewOutcomeSubmitting ? 'Creating…' : undefined}
                        onClick={() => submitNewOutcome()}
                    >
                        Create outcome
                    </LemonButton>
                </>
            }
        >
            <Form logic={outcomesLogic} formKey="newOutcome" className="deprecated-space-y-4">
                <LemonField name="name" label="Name">
                    <LemonInput placeholder="Activated" autoFocus />
                </LemonField>
                <LemonField name="description" label="Description" showOptional>
                    <LemonTextArea placeholder="What does reaching this outcome mean?" minRows={2} />
                </LemonField>
                <LemonField name="target_event" label="Target event">
                    <TaxonomicPopover
                        groupType={TaxonomicFilterGroupType.Events}
                        value={newOutcome.target_event}
                        onChange={(value) => setNewOutcomeValue('target_event', value ?? '')}
                        type="secondary"
                        placeholder="Select an event"
                        data-attr="outcome-event-picker"
                        renderValue={(v) =>
                            v ? (
                                <PropertyKeyInfo value={v} disablePopover type={TaxonomicFilterGroupType.Events} />
                            ) : null
                        }
                        excludedProperties={{ events: [null] }}
                        selectingKeyOnly
                    />
                </LemonField>
                <LemonField name="threshold" label="Threshold (at least this many occurrences)">
                    <LemonInput type="number" min={1} />
                </LemonField>
            </Form>
        </LemonModal>
    )
}
