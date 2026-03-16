import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { useMemo, useState } from 'react'

import { IconFlag, IconQuestion, IconTrash, IconX } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonMenu,
    LemonSelect,
    LemonSkeleton,
    LemonTag,
    Link,
} from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { FlagSelector } from 'lib/components/FlagSelector'
import { NotFound } from 'lib/components/NotFound'
import { SceneFile } from 'lib/components/Scenes/SceneFile'
import { SceneMetalyticsSummaryButton } from 'lib/components/Scenes/SceneMetalyticsSummaryButton'
import { SceneSelect } from 'lib/components/Scenes/SceneSelect'
import { useFileSystemLogView } from 'lib/hooks/useFileSystemLogView'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { JSONEditorInput } from 'scenes/feature-flags/JSONEditorInput'
import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import {
    ScenePanel,
    ScenePanelActionsSection,
    ScenePanelDivider,
    ScenePanelInfoSection,
} from '~/layout/scenes/SceneLayout'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { Query } from '~/queries/Query/Query'
import { Node, NodeKind, ProductIntentContext, ProductKey, QuerySchema } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import {
    CyclotronJobFiltersType,
    EarlyAccessFeatureStage,
    EarlyAccessFeatureTabs,
    EarlyAccessFeatureType,
    FilterLogicalOperator,
    PersonPropertyFilter,
    PropertyFilterType,
    PropertyOperator,
    RecordingUniversalFilters,
    ReplayTabs,
} from '~/types'

import { EarlyAccessFeatureLogicProps, earlyAccessFeatureLogic } from './earlyAccessFeatureLogic'
import { InstructionsModal } from './InstructionsModal'

const RESOURCE_TYPE = 'early-access-feature'

const ACTIVE_STAGES = new Set([
    EarlyAccessFeatureStage.Alpha,
    EarlyAccessFeatureStage.Beta,
    EarlyAccessFeatureStage.GeneralAvailability,
])

function StageTransitionWarning({
    from,
    to,
}: {
    from: EarlyAccessFeatureStage | null
    to: EarlyAccessFeatureStage
}): JSX.Element | null {
    if (!from || from === to) {
        return null
    }

    const wasActive = ACTIVE_STAGES.has(from)
    const willBeActive = ACTIVE_STAGES.has(to)

    if (to === EarlyAccessFeatureStage.GeneralAvailability) {
        return (
            <LemonBanner type="warning" className="mt-2">
                Promoting to general availability is permanent. The feature becomes read-only and the feature flag stays
                enabled for all opted-in users.
            </LemonBanner>
        )
    }

    if (!wasActive && willBeActive) {
        return (
            <LemonBanner type="warning" className="mt-2">
                This will enable the feature flag for all opted-in users. They will gain access to the feature when you
                save.
            </LemonBanner>
        )
    }

    if (wasActive && !willBeActive) {
        return (
            <LemonBanner type="warning" className="mt-2">
                This will disable the feature flag for opted-in users. They will lose access to the feature when you
                save.
            </LemonBanner>
        )
    }

    return null
}

export const scene: SceneExport<EarlyAccessFeatureLogicProps> = {
    component: EarlyAccessFeature,
    logic: earlyAccessFeatureLogic,
    paramsToProps: ({ params: { id } }) => ({
        id: id && id !== 'new' ? id : 'new',
    }),
    productKey: ProductKey.EARLY_ACCESS_FEATURES,
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
        showGAPromotionConfirmation,
        saveEarlyAccessFeature,
        setEarlyAccessFeatureValue,
    } = useActions(earlyAccessFeatureLogic)
    const { currentTeamId } = useValues(teamLogic)

    const isNewEarlyAccessFeature = id === 'new' || id === undefined

    // Determine if Save/Cancel buttons should be visible
    const wasOriginallyGA = originalEarlyAccessFeatureStage === EarlyAccessFeatureStage.GeneralAvailability
    const canShowSaveButtons = !wasOriginallyGA && (isNewEarlyAccessFeature || isEditingFeature)

    const earlyAccessFeatureId =
        earlyAccessFeature && 'id' in earlyAccessFeature && earlyAccessFeature.id !== 'new'
            ? earlyAccessFeature.id
            : null

    useFileSystemLogView({
        type: 'early_access_feature',
        ref: earlyAccessFeatureId,
        enabled: Boolean(currentTeamId && earlyAccessFeatureId && !earlyAccessFeatureLoading),
    })

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
            <SceneContent>
                <SceneTitleSection
                    name={earlyAccessFeature.name}
                    description={earlyAccessFeature.description}
                    resourceType={{
                        type: 'early_access_feature',
                    }}
                    canEdit={isNewEarlyAccessFeature || isEditingFeature}
                    onNameChange={(name) => {
                        setEarlyAccessFeatureValue('name', name)
                    }}
                    onDescriptionChange={(description) => {
                        setEarlyAccessFeatureValue('description', description)
                    }}
                    forceEdit={isEditingFeature || isNewEarlyAccessFeature}
                    actions={
                        <>
                            {!earlyAccessFeatureLoading ? (
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
                                            size="small"
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
                                                    earlyAccessFeature.stage ===
                                                    EarlyAccessFeatureStage.GeneralAvailability

                                                if (isPromotingToGA) {
                                                    showGAPromotionConfirmation((rolloutToAll: boolean) =>
                                                        submitEarlyAccessFeatureRequest({
                                                            ...earlyAccessFeature,
                                                            ...(rolloutToAll ? { rollout_to_all: true } : {}),
                                                        })
                                                    )
                                                } else {
                                                    submitEarlyAccessFeatureRequest(earlyAccessFeature)
                                                }
                                            }}
                                            loading={isEarlyAccessFeatureSubmitting}
                                            form="early-access-feature"
                                            size="small"
                                        >
                                            {isNewEarlyAccessFeature ? 'Save as draft' : 'Save'}
                                        </LemonButton>
                                    </>
                                ) : (
                                    <>
                                        {earlyAccessFeature.stage == EarlyAccessFeatureStage.Draft && (
                                            <LemonMenu
                                                items={[
                                                    {
                                                        title: 'Choose stage',
                                                        items: [
                                                            {
                                                                label: 'Concept',
                                                                tooltip:
                                                                    'Users can opt in to register interest, but the feature flag will not be enabled for them.',
                                                                onClick: () =>
                                                                    updateStage(EarlyAccessFeatureStage.Concept),
                                                            },
                                                            {
                                                                label: 'Alpha',
                                                                tooltip:
                                                                    'Early testing. Opted-in users will have the feature flag enabled.',
                                                                onClick: () =>
                                                                    updateStage(EarlyAccessFeatureStage.Alpha),
                                                            },
                                                            {
                                                                label: 'Beta (default)',
                                                                tooltip:
                                                                    'Wider testing. Opted-in users will have the feature flag enabled.',
                                                                onClick: () =>
                                                                    updateStage(EarlyAccessFeatureStage.Beta),
                                                            },
                                                            {
                                                                label: 'General availability',
                                                                tooltip:
                                                                    'Feature becomes read-only. All opted-in users retain access.',
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
                                                    size="small"
                                                >
                                                    Release
                                                </LemonButton>
                                            </LemonMenu>
                                        )}
                                        {earlyAccessFeature.stage != EarlyAccessFeatureStage.GeneralAvailability && (
                                            <LemonButton
                                                type="secondary"
                                                onClick={() => editFeature(true)}
                                                loading={false}
                                                data-attr="edit-feature"
                                                size="small"
                                            >
                                                Edit
                                            </LemonButton>
                                        )}
                                    </>
                                )
                            ) : undefined}
                        </>
                    }
                />

                <ScenePanel>
                    <ScenePanelInfoSection>
                        <SceneSelect
                            onSave={(value) => {
                                // Check if user is promoting to General Availability
                                const isPromotingToGA = value === EarlyAccessFeatureStage.GeneralAvailability

                                if (isPromotingToGA) {
                                    showGAPromotionConfirmation((rolloutToAll: boolean) =>
                                        saveEarlyAccessFeature({
                                            ...earlyAccessFeature,
                                            stage: value as EarlyAccessFeatureStage,
                                            ...(rolloutToAll ? { rollout_to_all: true } : {}),
                                        })
                                    )
                                } else {
                                    saveEarlyAccessFeature({
                                        ...earlyAccessFeature,
                                        stage: value as EarlyAccessFeatureStage,
                                    })
                                }
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
                                    label: 'General availability',
                                    value: 'general-availability',
                                },
                            ]}
                        />
                        <SceneFile dataAttrKey={RESOURCE_TYPE} />
                        <Link
                            to="https://posthog.com/docs/feature-flags/early-access-feature-management"
                            target="_blank"
                            className="text-xs"
                        >
                            Learn more about early access features
                        </Link>
                    </ScenePanelInfoSection>

                    <ScenePanelDivider />

                    <ScenePanelActionsSection>
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
                    </ScenePanelActionsSection>
                </ScenePanel>

                {!isEditingFeature && earlyAccessFeature.stage === EarlyAccessFeatureStage.Concept && (
                    <LemonBanner type="info">
                        The{' '}
                        <LemonTag type="default" className="uppercase">
                            Concept
                        </LemonTag>{' '}
                        stage is for gathering interest. Users can opt in, but the feature flag will not be enabled
                        until you promote this feature to Alpha or later. This lets you gauge demand before releasing
                        any functionality.
                    </LemonBanner>
                )}
                {!isEditingFeature && earlyAccessFeature.stage === EarlyAccessFeatureStage.Alpha && (
                    <LemonBanner type="info">
                        Opted-in users have the feature flag enabled for early testing. When you change the stage,
                        enrolled users will receive a notification event (<code>$feature_enrollment_update</code>).
                    </LemonBanner>
                )}
                {!isEditingFeature && earlyAccessFeature.stage === EarlyAccessFeatureStage.Beta && (
                    <LemonBanner type="info">
                        Opted-in users have the feature flag enabled for wider testing. When you change the stage,
                        enrolled users will receive a notification event (<code>$feature_enrollment_update</code>).
                    </LemonBanner>
                )}
                {!isEditingFeature && earlyAccessFeature.stage === EarlyAccessFeatureStage.GeneralAvailability && (
                    <LemonBanner type="success">
                        This feature has been promoted to general availability and can no longer be edited. Opted-in
                        users retain access via the feature flag.
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
                            help="A feature flag will be generated from the feature name if not provided"
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
                                <>
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
                                    <StageTransitionWarning
                                        from={originalEarlyAccessFeatureStage}
                                        to={earlyAccessFeature.stage}
                                    />
                                </>
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

                {isEditingFeature || isNewEarlyAccessFeature ? (
                    <div className="max-w-prose">
                        <LemonField
                            name="payload"
                            label="Payload"
                            showOptional
                            help={
                                <>
                                    This payload is delivered via the Early Access Features API and{' '}
                                    <code>posthog-js</code> when users browse available features. It is{' '}
                                    <strong>separate from the feature flag payload</strong>, which is returned during
                                    flag evaluation. Use this for metadata like release notes or UI configuration that
                                    your opt-in interface can display.{' '}
                                    <Link
                                        to="https://posthog.com/docs/feature-flags/early-access-feature-management"
                                        target="_blank"
                                    >
                                        Learn more
                                    </Link>
                                </>
                            }
                        >
                            <JSONEditorInput placeholder='{"key": "value", "anotherKey": {"nested": "object"}}' />
                        </LemonField>
                    </div>
                ) : (
                    <div className="max-w-prose">
                        <b>Payload</b>
                        <div>
                            {earlyAccessFeature.payload && Object.keys(earlyAccessFeature.payload).length > 0 ? (
                                <JSONEditorInput readOnly value={earlyAccessFeature.payload} />
                            ) : (
                                <span className="text-secondary">
                                    No payload configured. Payloads let you attach metadata (like release notes) that is
                                    delivered to users via the Early Access Features API.
                                </span>
                            )}
                        </div>
                    </div>
                )}

                {destinationFilters && (
                    <>
                        <SceneDivider />
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
                        <SceneDivider />
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

    return (
        <>
            <LemonTabs
                activeKey={activeTab}
                onChange={(newKey) => setActiveTab(newKey)}
                sceneInset
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
            select: defaultDataTableColumns(NodeKind.ActorsQuery),
            fixedProperties: properties,
        },
        full: true,
        propertiesViaUrl: false,
    })

    const { addProductIntentForCrossSell } = useActions(teamLogic)

    const context: QueryContext = useMemo(
        () => ({
            columns: {
                person_display_name: {
                    render: ({ value }) => {
                        const person = value as { id: string; display_name: string }
                        return (
                            <CopyToClipboardInline
                                explicitValue={person.display_name}
                                iconSize="small"
                                iconStyle={{ color: 'var(--color-accent)' }}
                            >
                                <PersonDisplay
                                    withIcon
                                    person={{ id: person.id }}
                                    displayName={person.display_name}
                                    noPopover
                                />
                            </CopyToClipboardInline>
                        )
                    },
                },
            },
        }),
        []
    )

    return (
        <div className="relative">
            {/*
            NOTE: This is a bit of a placement hack - ideally we would be able to add it to the Query
            UPDATE: Absolute postion was overlapping with filters, so we put a bit on top. Still need to find a better solution.
             */}
            <div className="flex justify-end mb-2">
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
            <Query query={query} setQuery={setQuery} context={context} />
        </div>
    )
}
