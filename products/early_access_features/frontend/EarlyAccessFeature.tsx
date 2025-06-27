import { IconFlag, IconQuestion, IconX } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDivider,
    LemonInput,
    LemonMenu,
    LemonSelect,
    LemonSkeleton,
    LemonTag,
    LemonTextArea,
    Link,
} from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { FlagSelector } from 'lib/components/FlagSelector'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { ProductIntentContext } from 'lib/utils/product-intents'
import { useState } from 'react'
import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { Node, NodeKind, QuerySchema } from '~/queries/schema/schema-general'
import {
    CyclotronJobFiltersType,
    EarlyAccessFeatureStage,
    EarlyAccessFeatureTabs,
    EarlyAccessFeatureType,
    FilterLogicalOperator,
    PersonPropertyFilter,
    ProductKey,
    PropertyFilterType,
    PropertyOperator,
    RecordingUniversalFilters,
    ReplayTabs,
} from '~/types'

import { earlyAccessFeatureLogic } from './earlyAccessFeatureLogic'
import { InstructionsModal } from './InstructionsModal'

export const scene: SceneExport = {
    component: EarlyAccessFeature,
    logic: earlyAccessFeatureLogic,
    paramsToProps: ({ params: { id } }): (typeof earlyAccessFeatureLogic)['props'] => ({
        id: id && id !== 'new' ? id : 'new',
    }),
    settingSectionId: 'environment-feature-flags',
}

export function EarlyAccessFeature({ id }: { id?: string } = {}): JSX.Element {
    const {
        earlyAccessFeature,
        earlyAccessFeatureLoading,
        isEarlyAccessFeatureSubmitting,
        isEditingFeature,
        earlyAccessFeatureMissing,
        implementOptInInstructionsModal,
    } = useValues(earlyAccessFeatureLogic)
    const {
        submitEarlyAccessFeatureRequest,
        loadEarlyAccessFeature,
        editFeature,
        updateStage,
        deleteEarlyAccessFeature,
        toggleImplementOptInInstructionsModal,
    } = useActions(earlyAccessFeatureLogic)

    const isNewEarlyAccessFeature = id === 'new' || id === undefined

    if (earlyAccessFeatureMissing) {
        return <NotFound object="early access feature" />
    }

    if (earlyAccessFeatureLoading) {
        return <LemonSkeleton active />
    }

    const destinationFilters: CyclotronJobFiltersType | null =
        !isEditingFeature && !isNewEarlyAccessFeature && 'id' in earlyAccessFeature
            ? {
                  events: [
                      {
                          id: '$feature_enrollment_update',
                          type: 'events',
                          properties: [
                              {
                                  key: '$feature_flag',
                                  value: [earlyAccessFeature.feature_flag.key],
                                  operator: PropertyOperator.Exact,
                                  type: PropertyFilterType.Event,
                              },
                          ],
                      },
                  ],
              }
            : null

    return (
        <Form id="early-access-feature" formKey="earlyAccessFeature" logic={earlyAccessFeatureLogic}>
            <PageHeader
                buttons={
                    !earlyAccessFeatureLoading ? (
                        earlyAccessFeature.stage != EarlyAccessFeatureStage.GeneralAvailability &&
                        (isNewEarlyAccessFeature || isEditingFeature) ? (
                            <>
                                <LemonButton
                                    type="secondary"
                                    data-attr="cancel-feature"
                                    onClick={() => {
                                        if (isEditingFeature) {
                                            editFeature(false)
                                            loadEarlyAccessFeature()
                                        } else {
                                            router.actions.push(urls.earlyAccessFeatures())
                                        }
                                    }}
                                    disabledReason={isEarlyAccessFeatureSubmitting ? 'Saving…' : undefined}
                                >
                                    Cancel
                                </LemonButton>
                                <LemonButton
                                    type="primary"
                                    htmlType="submit"
                                    data-attr="save-feature"
                                    onClick={() => {
                                        submitEarlyAccessFeatureRequest(earlyAccessFeature)
                                    }}
                                    loading={isEarlyAccessFeatureSubmitting}
                                    form="early-access-feature"
                                >
                                    {isNewEarlyAccessFeature ? 'Save as draft' : 'Save'}
                                </LemonButton>
                            </>
                        ) : (
                            <>
                                <LemonButton
                                    data-attr="delete-feature"
                                    status="danger"
                                    type="secondary"
                                    onClick={() => {
                                        LemonDialog.open({
                                            title: 'Permanently delete feature?',
                                            description:
                                                'Doing so will remove any opt in conditions from the feature flag.',
                                            primaryButton: {
                                                children: 'Delete',
                                                type: 'primary',
                                                status: 'danger',
                                                'data-attr': 'confirm-delete-feature',
                                                onClick: () => {
                                                    // conditional above ensures earlyAccessFeature is not NewEarlyAccessFeature
                                                    deleteEarlyAccessFeature(
                                                        (earlyAccessFeature as EarlyAccessFeatureType)?.id
                                                    )
                                                },
                                            },
                                            secondaryButton: {
                                                children: 'Close',
                                                type: 'secondary',
                                            },
                                        })
                                    }}
                                >
                                    Delete
                                </LemonButton>
                                {earlyAccessFeature.stage == EarlyAccessFeatureStage.Beta && (
                                    <LemonButton
                                        data-attr="archive-feature"
                                        type="secondary"
                                        onClick={() => updateStage(EarlyAccessFeatureStage.Archived)}
                                    >
                                        Archive
                                    </LemonButton>
                                )}
                                {earlyAccessFeature.stage == EarlyAccessFeatureStage.Archived && (
                                    <LemonButton
                                        data-attr="reactive-feature"
                                        type="secondary"
                                        onClick={() => updateStage(EarlyAccessFeatureStage.Beta)}
                                    >
                                        Reactivate beta
                                    </LemonButton>
                                )}
                                {earlyAccessFeature.stage == EarlyAccessFeatureStage.Draft && (
                                    <LemonMenu
                                        items={[
                                            {
                                                title: 'Choose stage',
                                                items: [
                                                    {
                                                        label: 'Concept',
                                                        onClick: () => updateStage(EarlyAccessFeatureStage.Concept),
                                                    },
                                                    {
                                                        label: 'Alpha',
                                                        onClick: () => updateStage(EarlyAccessFeatureStage.Alpha),
                                                    },
                                                    {
                                                        label: 'Beta (default)',
                                                        onClick: () => updateStage(EarlyAccessFeatureStage.Beta),
                                                    },
                                                    {
                                                        label: 'General availability',
                                                        onClick: () =>
                                                            updateStage(EarlyAccessFeatureStage.GeneralAvailability),
                                                    },
                                                ],
                                            },
                                        ]}
                                    >
                                        <LemonButton tooltip="Publish this feature to make it available" type="primary">
                                            Release
                                        </LemonButton>
                                    </LemonMenu>
                                )}
                                <LemonDivider vertical />
                                {earlyAccessFeature.stage != EarlyAccessFeatureStage.GeneralAvailability && (
                                    <LemonButton
                                        type="secondary"
                                        onClick={() => editFeature(true)}
                                        loading={false}
                                        data-attr="edit-feature"
                                    >
                                        Edit
                                    </LemonButton>
                                )}
                            </>
                        )
                    ) : undefined
                }
            />
            <div className={clsx(isEditingFeature || isNewEarlyAccessFeature ? 'max-w-160' : null)}>
                <div className="flex flex-col gap-4 flex-2 min-w-[15rem]">
                    {isNewEarlyAccessFeature && (
                        <LemonField name="name" label="Name">
                            <LemonInput data-attr="feature-name" />
                        </LemonField>
                    )}

                    {earlyAccessFeature.stage === EarlyAccessFeatureStage.Concept && !isEditingFeature && (
                        <LemonBanner type="info">
                            The{' '}
                            <LemonTag type="default" className="uppercase">
                                Concept
                            </LemonTag>{' '}
                            stage assigns the feature flag to the user. Gate your code behind a different feature flag
                            if you'd like to keep it hidden, and then switch your code to this feature flag when you're
                            ready to release to your early access users.
                        </LemonBanner>
                    )}
                    <div className="flex flex-wrap gap-4 items-start">
                        <div className="flex-1 min-w-[20rem]">
                            {'feature_flag' in earlyAccessFeature ? (
                                <LemonField.Pure label="Connected Feature flag">
                                    <div>
                                        <LemonButton
                                            type="secondary"
                                            onClick={() =>
                                                earlyAccessFeature.feature_flag &&
                                                router.actions.push(
                                                    urls.featureFlag(earlyAccessFeature.feature_flag.id)
                                                )
                                            }
                                            icon={<IconFlag />}
                                        >
                                            {earlyAccessFeature.feature_flag.key}
                                        </LemonButton>
                                    </div>
                                </LemonField.Pure>
                            ) : (
                                <LemonField
                                    name="feature_flag_id"
                                    label="Link feature flag (optional)"
                                    info={<>A feature flag will be generated from feature name if not provided</>}
                                >
                                    {({ value, onChange }) => (
                                        <div className="flex">
                                            <FlagSelector value={value} onChange={onChange} />
                                            {value && (
                                                <LemonButton
                                                    className="ml-2"
                                                    icon={<IconX />}
                                                    size="small"
                                                    onClick={() => onChange(undefined)}
                                                    aria-label="close"
                                                />
                                            )}
                                        </div>
                                    )}
                                </LemonField>
                            )}
                        </div>

                        {!isNewEarlyAccessFeature && earlyAccessFeature.stage !== 'draft' ? (
                            <div className="flex-1 min-w-[20rem]">
                                <b>Stage</b>
                                <div>
                                    {isEditingFeature ? (
                                        <LemonField name="stage">
                                            <LemonSelect
                                                options={[
                                                    {
                                                        value: 'concept',
                                                        label: 'Concept',
                                                    },
                                                    {
                                                        value: 'alpha',
                                                        label: 'Alpha',
                                                    },
                                                    {
                                                        value: 'beta',
                                                        label: 'Beta',
                                                    },
                                                    {
                                                        value: 'general-availability',
                                                        label: 'General availability',
                                                    },
                                                ]}
                                            />
                                        </LemonField>
                                    ) : (
                                        <LemonTag
                                            type={
                                                earlyAccessFeature.stage === EarlyAccessFeatureStage.Beta
                                                    ? 'warning'
                                                    : earlyAccessFeature.stage ===
                                                      EarlyAccessFeatureStage.GeneralAvailability
                                                    ? 'success'
                                                    : 'default'
                                            }
                                            className="mt-2 uppercase"
                                        >
                                            {earlyAccessFeature.stage}
                                        </LemonTag>
                                    )}
                                </div>
                            </div>
                        ) : null}
                    </div>
                    <div className="flex flex-wrap gap-4 items-start">
                        <div className="flex-1 min-w-[20rem]">
                            {isEditingFeature || isNewEarlyAccessFeature ? (
                                <LemonField name="description" label="Description" showOptional>
                                    <LemonTextArea
                                        className="ph-ignore-input"
                                        placeholder="Help your users understand the feature"
                                    />
                                </LemonField>
                            ) : (
                                <div className="mb-2">
                                    <b>Description</b>
                                    <div>
                                        {earlyAccessFeature.description ? (
                                            earlyAccessFeature.description
                                        ) : (
                                            <span className="text-secondary">No description</span>
                                        )}
                                    </div>
                                </div>
                            )}
                        </div>
                        <div className="flex-1 min-w-[20rem]">
                            {isEditingFeature || isNewEarlyAccessFeature ? (
                                <LemonField name="documentation_url" label="Documentation URL" showOptional>
                                    <LemonInput
                                        autoComplete="off"
                                        autoCapitalize="off"
                                        autoCorrect="off"
                                        spellCheck={false}
                                    />
                                </LemonField>
                            ) : (
                                <div className="mb-2">
                                    <b>Documentation URL</b>
                                    <div>
                                        {earlyAccessFeature.documentation_url ? (
                                            <Link to={earlyAccessFeature.documentation_url} target="_blank">
                                                {earlyAccessFeature.documentation_url}
                                            </Link>
                                        ) : (
                                            <span className="text-secondary">No documentation URL</span>
                                        )}
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>
                </div>
                {destinationFilters && (
                    <>
                        <LemonDivider className="my-8" />
                        <h3>Notifications</h3>
                        <p>Get notified when people opt in or out of your feature.</p>
                        <LinkedHogFunctions
                            type="destination"
                            forceFilterGroups={[destinationFilters]}
                            subTemplateIds={['early-access-feature-enrollment']}
                        />
                    </>
                )}
                {!isEditingFeature && !isNewEarlyAccessFeature && 'id' in earlyAccessFeature && (
                    <>
                        <LemonDivider className="my-8" />
                        <div className="flex gap-4 justify-between items-start">
                            <div>
                                <h3>Users</h3>
                                <p>
                                    When a user opts in or out of the feature they will be listed here. You can choose
                                    to{' '}
                                    <Link onClick={toggleImplementOptInInstructionsModal}>
                                        implement your own opt-in interface or use our provided app.
                                    </Link>
                                </p>
                            </div>
                            <LemonButton
                                key="help-button"
                                onClick={toggleImplementOptInInstructionsModal}
                                sideIcon={<IconQuestion />}
                                type="secondary"
                            >
                                Implement public opt-in
                            </LemonButton>
                        </div>
                        <PersonList earlyAccessFeature={earlyAccessFeature} />
                    </>
                )}
            </div>

            {'id' in earlyAccessFeature ? (
                <InstructionsModal
                    flag={earlyAccessFeature.feature_flag.key}
                    visible={implementOptInInstructionsModal}
                    onClose={toggleImplementOptInInstructionsModal}
                />
            ) : null}
        </Form>
    )
}

interface PersonListProps {
    earlyAccessFeature: EarlyAccessFeatureType
}

function featureFlagRecordingEnrollmentFilter(
    earlyAccessFeature: EarlyAccessFeatureType,
    optedIn: boolean
): Partial<RecordingUniversalFilters> {
    return {
        filter_group: {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: 'events',
                            order: 0,
                            id: '$feature_enrollment_update',
                            name: '$feature_enrollment_update',
                            properties: [
                                {
                                    key: '$feature_enrollment',
                                    value: [optedIn ? 'true' : 'false'],
                                    operator: PropertyOperator.Exact,
                                    type: PropertyFilterType.Event,
                                },
                                {
                                    key: '$feature_flag',
                                    value: [earlyAccessFeature.feature_flag.key],
                                    operator: PropertyOperator.Exact,
                                    type: PropertyFilterType.Event,
                                },
                            ],
                        },
                    ],
                },
            ],
        },
    }
}

export function PersonList({ earlyAccessFeature }: PersonListProps): JSX.Element {
    const { activeTab, optedInCount, optedOutCount, featureEnrollmentKey } = useValues(earlyAccessFeatureLogic)
    const { setActiveTab } = useActions(earlyAccessFeatureLogic)

    return (
        <>
            <LemonTabs
                activeKey={activeTab}
                onChange={(newKey) => setActiveTab(newKey)}
                tabs={[
                    {
                        key: EarlyAccessFeatureTabs.OptedIn,
                        label: optedInCount !== null ? `Opted-In Users (${optedInCount})` : 'Opted-In Users',
                        content: (
                            <>
                                <PersonsTableByFilter
                                    recordingsFilters={featureFlagRecordingEnrollmentFilter(earlyAccessFeature, true)}
                                    properties={[
                                        {
                                            key: featureEnrollmentKey,
                                            type: PropertyFilterType.Person,
                                            operator: PropertyOperator.Exact,
                                            value: ['true'],
                                        },
                                    ]}
                                />
                            </>
                        ),
                    },
                    {
                        key: EarlyAccessFeatureTabs.OptedOut,
                        label: optedOutCount !== null ? `Opted-Out Users (${optedOutCount})` : 'Opted-Out Users',
                        content: (
                            <PersonsTableByFilter
                                recordingsFilters={featureFlagRecordingEnrollmentFilter(earlyAccessFeature, false)}
                                properties={[
                                    {
                                        key: featureEnrollmentKey,
                                        type: PropertyFilterType.Person,
                                        operator: PropertyOperator.Exact,
                                        value: ['false'],
                                    },
                                ]}
                            />
                        ),
                    },
                ]}
            />
        </>
    )
}

interface PersonsTableByFilterProps {
    properties: PersonPropertyFilter[]
    recordingsFilters: Partial<RecordingUniversalFilters>
}

function PersonsTableByFilter({ recordingsFilters, properties }: PersonsTableByFilterProps): JSX.Element {
    const [query, setQuery] = useState<Node | QuerySchema>({
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.ActorsQuery,
            fixedProperties: properties,
        },
        full: true,
        propertiesViaUrl: false,
    })

    const { addProductIntentForCrossSell } = useActions(teamLogic)

    return (
        <div className="relative">
            {/* NOTE: This is a bit of a placement hack - ideally we would be able to add it to the Query */}
            <div className="absolute top-0 right-0 z-10">
                <LemonButton
                    key="view-opt-in-session-recordings"
                    to={urls.replay(ReplayTabs.Home, recordingsFilters)}
                    onClick={() => {
                        addProductIntentForCrossSell({
                            from: ProductKey.EARLY_ACCESS_FEATURES,
                            to: ProductKey.SESSION_REPLAY,
                            intent_context: ProductIntentContext.EARLY_ACCESS_FEATURE_VIEW_RECORDINGS,
                        })
                    }}
                    type="secondary"
                >
                    View recordings
                </LemonButton>
            </div>
            <Query query={query} setQuery={setQuery} />
        </div>
    )
}
