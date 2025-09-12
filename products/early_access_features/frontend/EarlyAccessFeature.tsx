import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconFlag, IconQuestion, IconTrash, IconX } from '@posthog/icons'
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

import { FlagSelector } from 'lib/components/FlagSelector'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneFile } from 'lib/components/Scenes/SceneFile'
import { SceneMetalyticsSummaryButton } from 'lib/components/Scenes/SceneMetalyticsSummaryButton'
import { SceneSelect } from 'lib/components/Scenes/SceneSelect'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ProductIntentContext } from 'lib/utils/product-intents'
import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ScenePanel, ScenePanelActions, ScenePanelDivider, ScenePanelMetaInfo } from '~/layout/scenes/SceneLayout'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
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

import { InstructionsModal } from './InstructionsModal'
import { EarlyAccessFeatureLogicProps, earlyAccessFeatureLogic } from './earlyAccessFeatureLogic'

const RESOURCE_TYPE = 'early-access-feature'

export const scene: SceneExport<EarlyAccessFeatureLogicProps> = {
    component: EarlyAccessFeature,
    logic: earlyAccessFeatureLogic,
    paramsToProps: ({ params: { id } }) => ({
        id: id && id !== 'new' ? id : 'new',
    }),
    settingSectionId: 'environment-feature-flags',
}

export function EarlyAccessFeature({ id }: EarlyAccessFeatureLogicProps): JSX.Element {
    const {
        earlyAccessFeature,
        earlyAccessFeatureLoading,
        isEarlyAccessFeatureSubmitting,
        isEditingFeature,
        earlyAccessFeatureMissing,
        implementOptInInstructionsModal,
        originalEarlyAccessFeatureStage,
    } = useValues(earlyAccessFeatureLogic)
    const {
        submitEarlyAccessFeatureRequest,
        loadEarlyAccessFeature,
        editFeature,
        updateStage,
        deleteEarlyAccessFeature,
        toggleImplementOptInInstructionsModal,
        setEarlyAccessFeatureValue,
        showGAPromotionConfirmation,
    } = useActions(earlyAccessFeatureLogic)

    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')

    const isNewEarlyAccessFeature = id === 'new' || id === undefined

    // Determine if Save/Cancel buttons should be visible
    const wasOriginallyGA = originalEarlyAccessFeatureStage === EarlyAccessFeatureStage.GeneralAvailability
    const canShowSaveButtons = !wasOriginallyGA && (isNewEarlyAccessFeature || isEditingFeature)

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
            <SceneContent forceNewSpacing>
                <PageHeader
                    buttons={
                        !earlyAccessFeatureLoading ? (
                            canShowSaveButtons ? (
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
                                            // Check if user is promoting to General Availability
                                            const isPromotingToGA =
                                                earlyAccessFeature.stage === EarlyAccessFeatureStage.GeneralAvailability

                                            if (isPromotingToGA) {
                                                showGAPromotionConfirmation(() =>
                                                    submitEarlyAccessFeatureRequest(earlyAccessFeature)
                                                )
                                            } else {
                                                submitEarlyAccessFeatureRequest(earlyAccessFeature)
                                            }
                                        }}
                                        loading={isEarlyAccessFeatureSubmitting}
                                        form="early-access-feature"
                                    >
                                        {isNewEarlyAccessFeature ? 'Save as draft' : 'Save'}
                                    </LemonButton>
                                </>
                            ) : (
                                <>
                                    {!newSceneLayout && (
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
                                    )}
                                    {!newSceneLayout && earlyAccessFeature.stage == EarlyAccessFeatureStage.Beta && (
                                        <LemonButton
                                            data-attr="archive-feature"
                                            type="secondary"
                                            onClick={() => updateStage(EarlyAccessFeatureStage.Archived)}
                                        >
                                            Archive
                                        </LemonButton>
                                    )}
                                    {!newSceneLayout &&
                                        earlyAccessFeature.stage == EarlyAccessFeatureStage.Archived && (
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
                                                            label: 'General availability / Archived',
                                                            onClick: () =>
                                                                updateStage(
                                                                    EarlyAccessFeatureStage.GeneralAvailability
                                                                ),
                                                        },
                                                    ],
                                                },
                                            ]}
                                        >
                                            <LemonButton
                                                tooltip="Publish this feature to make it available"
                                                type="primary"
                                            >
                                                Release
                                            </LemonButton>
                                        </LemonMenu>
                                    )}
                                    {!newSceneLayout && <LemonDivider vertical />}
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

                <SceneTitleSection
                    name={earlyAccessFeature.name}
                    description={earlyAccessFeature.description}
                    resourceType={{
                        type: 'early_access_feature',
                    }}
                    canEdit
                    onNameChange={(value) => {
                        setEarlyAccessFeatureValue('name', value)
                    }}
                    onDescriptionChange={(value) => {
                        setEarlyAccessFeatureValue('description', value)
                    }}
                    forceEdit={isEditingFeature || isNewEarlyAccessFeature}
                />

                <SceneDivider />

                <ScenePanel>
                    <ScenePanelMetaInfo>
                        <SceneSelect
                            onSave={(value) => {
                                setEarlyAccessFeatureValue('stage', value)
                            }}
                            value={earlyAccessFeature.stage}
                            name="stage"
                            dataAttrKey={RESOURCE_TYPE}
                            options={[
                                {
                                    label: 'Draft (default)',
                                    value: 'draft',
                                    disabled: true,
                                },
                                {
                                    label: 'Concept',
                                    value: 'concept',
                                },
                                {
                                    label: 'Alpha',
                                    value: 'alpha',
                                },
                                {
                                    label: 'Beta',
                                    value: 'beta',
                                },
                                {
                                    label: 'General availability / Archived',
                                    value: 'general-availability',
                                },
                            ]}
                        />
                        <SceneFile dataAttrKey={RESOURCE_TYPE} />
                    </ScenePanelMetaInfo>

                    <ScenePanelDivider />

                    <ScenePanelActions>
                        <SceneMetalyticsSummaryButton dataAttrKey={RESOURCE_TYPE} />
                        <ScenePanelDivider />
                        <ButtonPrimitive
                            onClick={() => {
                                LemonDialog.open({
                                    title: 'Permanently delete feature?',
                                    description: 'Doing so will remove any opt in conditions from the feature flag.',
                                    primaryButton: {
                                        children: 'Delete',
                                        type: 'primary',
                                        status: 'danger',
                                        'data-attr': 'confirm-delete-feature',
                                        onClick: () => {
                                            // conditional above ensures earlyAccessFeature is not NewEarlyAccessFeature
                                            deleteEarlyAccessFeature((earlyAccessFeature as EarlyAccessFeatureType)?.id)
                                        },
                                    },
                                    secondaryButton: {
                                        children: 'Close',
                                        type: 'secondary',
                                    },
                                })
                            }}
                            variant="danger"
                            menuItem
                            data-attr={`${RESOURCE_TYPE}-delete`}
                        >
                            <IconTrash />
                            Delete
                        </ButtonPrimitive>
                    </ScenePanelActions>
                </ScenePanel>

                {!newSceneLayout && isNewEarlyAccessFeature && (
                    <LemonField name="name" label="Name" className="max-w-prose">
                        <LemonInput data-attr="feature-name" />
                    </LemonField>
                )}

                {earlyAccessFeature.stage === EarlyAccessFeatureStage.Concept && !isEditingFeature && (
                    <LemonBanner type="info">
                        The{' '}
                        <LemonTag type="default" className="uppercase">
                            Concept
                        </LemonTag>{' '}
                        stage assigns the feature flag to the user. Gate your code behind a different feature flag if
                        you'd like to keep it hidden, and then switch your code to this feature flag when you're ready
                        to release to your early access users.
                    </LemonBanner>
                )}
                <div className="flex-1 min-w-[20rem] max-w-prose">
                    {'feature_flag' in earlyAccessFeature ? (
                        <LemonField.Pure label="Connected Feature flag">
                            <div>
                                <LemonButton
                                    type="secondary"
                                    onClick={() =>
                                        earlyAccessFeature.feature_flag &&
                                        router.actions.push(urls.featureFlag(earlyAccessFeature.feature_flag.id))
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
                    <div className="flex-1 min-w-[20rem] max-w-prose">
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
                                                label: 'General availability / Archived',
                                            },
                                        ]}
                                    />
                                </LemonField>
                            ) : (
                                <LemonTag
                                    type={
                                        earlyAccessFeature.stage === EarlyAccessFeatureStage.Beta
                                            ? 'warning'
                                            : earlyAccessFeature.stage === EarlyAccessFeatureStage.GeneralAvailability
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

                {!newSceneLayout && (
                    <div className="flex-1 min-w-[20rem] max-w-prose">
                        {isEditingFeature || isNewEarlyAccessFeature ? (
                            <LemonField name="description" label="Description" showOptional>
                                <LemonTextArea
                                    className="ph-ignore-input"
                                    placeholder="Help your users understand the feature"
                                />
                            </LemonField>
                        ) : (
                            <div>
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
                )}

                {isEditingFeature || isNewEarlyAccessFeature ? (
                    <div className="max-w-prose">
                        <LemonField name="documentation_url" label="Documentation URL" showOptional>
                            <LemonInput autoComplete="off" autoCapitalize="off" autoCorrect="off" spellCheck={false} />
                        </LemonField>
                    </div>
                ) : (
                    <div>
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

                {destinationFilters && (
                    <>
                        {newSceneLayout ? <SceneDivider /> : <LemonDivider className="my-4" />}
                        <SceneSection
                            title="Notifications"
                            description="Get notified when people opt in or out of your feature."
                        >
                            <LinkedHogFunctions
                                type="destination"
                                forceFilterGroups={[destinationFilters]}
                                subTemplateIds={['early-access-feature-enrollment']}
                            />
                        </SceneSection>
                    </>
                )}
                {!isEditingFeature && !isNewEarlyAccessFeature && 'id' in earlyAccessFeature && (
                    <>
                        {newSceneLayout ? <SceneDivider /> : <LemonDivider className="my-4" />}
                        <SceneSection
                            title="Users"
                            description={
                                <p>
                                    When a user opts in or out of the feature they will be listed here. You can choose
                                    to{' '}
                                    <Link onClick={toggleImplementOptInInstructionsModal}>
                                        implement your own opt-in interface or use our provided app.
                                    </Link>
                                </p>
                            }
                            actions={
                                <LemonButton
                                    key="help-button"
                                    onClick={toggleImplementOptInInstructionsModal}
                                    sideIcon={<IconQuestion />}
                                    type="secondary"
                                >
                                    Implement public opt-in
                                </LemonButton>
                            }
                        >
                            <PersonList earlyAccessFeature={earlyAccessFeature} />
                        </SceneSection>
                    </>
                )}

                {'id' in earlyAccessFeature ? (
                    <InstructionsModal
                        flag={earlyAccessFeature.feature_flag.key}
                        visible={implementOptInInstructionsModal}
                        onClose={toggleImplementOptInInstructionsModal}
                    />
                ) : null}
            </SceneContent>
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
    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')

    return (
        <>
            <LemonTabs
                activeKey={activeTab}
                onChange={(newKey) => setActiveTab(newKey)}
                sceneInset={newSceneLayout}
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
