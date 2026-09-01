import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonTable, LemonTag, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { createdAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { LemonTableColumn } from 'lib/lemon-ui/LemonTable/types'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType, EarlyAccessFeatureType } from '~/types'

import {
    AssigneeIconDisplay,
    AssigneeLabelDisplay,
    AssigneeResolver,
} from 'products/error_tracking/frontend/components/Assignee/AssigneeDisplay'
import { AssigneeSelect } from 'products/error_tracking/frontend/components/Assignee/AssigneeSelect'

import { earlyAccessFeaturesLogic, waitlistSurveyId } from './earlyAccessFeaturesLogic'
import { earlyAccessFeaturesEmptyState } from './emptyState/earlyAccessFeaturesEmptyState'

// Features with no waitlist survey sort below a real count of 0.
const NO_WAITLIST_SORT_VALUE = -1

export const scene: SceneExport = {
    component: EarlyAccessFeatures,
    logic: earlyAccessFeaturesLogic,
    productKey: ProductKey.EARLY_ACCESS_FEATURES,
    emptyState: earlyAccessFeaturesEmptyState,
}

const STAGES_IN_ORDER: Record<EarlyAccessFeatureType['stage'], number> = {
    draft: 0,
    concept: 1,
    alpha: 2,
    beta: 3,
    'general-availability': 4,
    archived: 5,
}

export function EarlyAccessFeatures(): JSX.Element {
    const {
        filteredEarlyAccessFeatures,
        earlyAccessFeaturesLoading,
        searchTerm,
        waitlistResponsesCount,
        waitlistResponsesCountLoading,
        waitlistResponsesCountFailed,
    } = useValues(earlyAccessFeaturesLogic)
    const { setSearchTerm, updateFeatureAssignee } = useActions(earlyAccessFeaturesLogic)

    // Creating an early access feature requires editor access to the resource.
    const accessControlDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.EarlyAccessFeature,
        AccessControlLevel.Editor
    )

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.EarlyAccessFeatures].name}
                description={sceneConfigurations[Scene.EarlyAccessFeatures].description}
                resourceType={{
                    type: sceneConfigurations[Scene.EarlyAccessFeatures].iconType || 'default_icon_type',
                }}
                actions={
                    <Shortcut
                        name="NewEarlyAccessFeature"
                        keybind={[keyBinds.new]}
                        intent="New early access feature"
                        interaction="click"
                        scope={Scene.EarlyAccessFeatures}
                    >
                        <LemonButton
                            size="small"
                            type="primary"
                            to={urls.earlyAccessFeature('new')}
                            tooltip="New feature"
                            data-attr="create-feature"
                            disabledReason={accessControlDisabledReason ?? undefined}
                        >
                            New feature
                        </LemonButton>
                    </Shortcut>
                }
            />

            <div className="mb-4">
                <LemonInput
                    type="search"
                    placeholder="Search early access features..."
                    value={searchTerm}
                    onChange={setSearchTerm}
                    allowClear
                />
            </div>
            <LemonTable
                loading={earlyAccessFeaturesLoading}
                columns={[
                    {
                        title: 'Name',
                        key: 'name',
                        render(_, feature) {
                            return (
                                <LemonTableLink
                                    title={feature.name}
                                    description={feature.description}
                                    to={urls.earlyAccessFeature(feature.id)}
                                />
                            )
                        },
                        sorter: (a, b) => a.name.localeCompare(b.name),
                    },
                    {
                        title: 'Stage',
                        dataIndex: 'stage',
                        render(_, { stage }) {
                            return (
                                <LemonTag
                                    type={
                                        stage === 'beta'
                                            ? 'warning'
                                            : stage === 'general-availability'
                                              ? 'success'
                                              : 'default'
                                    }
                                    className="uppercase cursor-default"
                                    data-attr="feature-stage"
                                >
                                    {stage}
                                </LemonTag>
                            )
                        },
                        sorter: (a, b) => STAGES_IN_ORDER[a.stage] - STAGES_IN_ORDER[b.stage],
                    },
                    {
                        title: 'Waitlist',
                        key: 'waitlist',
                        tooltip: 'People who signed up to the waitlist survey for this feature',
                        render(_, feature) {
                            const surveyId = waitlistSurveyId(feature)
                            if (surveyId === null) {
                                return <span className="text-secondary">–</span>
                            }
                            if (waitlistResponsesCountLoading) {
                                return <Spinner />
                            }
                            if (waitlistResponsesCountFailed) {
                                return (
                                    <Tooltip title="Couldn't load waitlist signups">
                                        <span className="text-secondary">–</span>
                                    </Tooltip>
                                )
                            }
                            const count = waitlistResponsesCount[surveyId] ?? 0
                            return (
                                <Link
                                    to={urls.survey(surveyId)}
                                    aria-label={`${count} waitlist signups for ${feature.name}`}
                                >
                                    {count}
                                </Link>
                            )
                        },
                        sorter: (a, b) => {
                            const getCount = (feature: EarlyAccessFeatureType): number => {
                                const surveyId = waitlistSurveyId(feature)
                                return surveyId !== null
                                    ? (waitlistResponsesCount[surveyId] ?? 0)
                                    : NO_WAITLIST_SORT_VALUE
                            }
                            return getCount(a) - getCount(b)
                        },
                    },
                    {
                        title: 'Assignee',
                        key: 'assignee',
                        render(_, feature) {
                            const assigneeEditDisabledReason = getAccessControlDisabledReason(
                                AccessControlResourceType.EarlyAccessFeature,
                                AccessControlLevel.Editor,
                                feature.user_access_level
                            )
                            // AssigneeSelect opens its dropdown from a wrapper the disabled button
                            // can't gate, so viewers get a read-only display instead of a live trigger.
                            if (assigneeEditDisabledReason) {
                                return (
                                    <AssigneeResolver assignee={feature.assignee ?? null}>
                                        {({ assignee: resolvedAssignee }) => (
                                            <Tooltip title={assigneeEditDisabledReason}>
                                                <span className="flex items-center gap-1">
                                                    <AssigneeIconDisplay assignee={resolvedAssignee} size="small" />
                                                    <AssigneeLabelDisplay assignee={resolvedAssignee} size="small" />
                                                </span>
                                            </Tooltip>
                                        )}
                                    </AssigneeResolver>
                                )
                            }
                            return (
                                <AssigneeSelect
                                    assignee={feature.assignee ?? null}
                                    onChange={(assignee) => updateFeatureAssignee(feature.id, assignee)}
                                >
                                    {(displayAssignee) => (
                                        <LemonButton
                                            type="tertiary"
                                            size="small"
                                            data-attr="early-access-feature-list-assignee"
                                        >
                                            <AssigneeIconDisplay assignee={displayAssignee} size="small" />
                                            <AssigneeLabelDisplay assignee={displayAssignee} size="small" />
                                        </LemonButton>
                                    )}
                                </AssigneeSelect>
                            )
                        },
                    },
                    createdAtColumn<EarlyAccessFeatureType>() as LemonTableColumn<
                        EarlyAccessFeatureType,
                        keyof EarlyAccessFeatureType | undefined
                    >,
                ]}
                dataSource={filteredEarlyAccessFeatures}
                emptyState={
                    searchTerm ? (
                        <div className="text-center py-8">No early access features match your search</div>
                    ) : undefined
                }
            />
        </SceneContent>
    )
}
