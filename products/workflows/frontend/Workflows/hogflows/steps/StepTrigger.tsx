import { Node } from '@xyflow/react'
import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import {
    IconBolt,
    IconButton,
    IconClock,
    IconInfo,
    IconLeave,
    IconPeople,
    IconTarget,
    IconWarning,
    IconWebhooks,
} from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonCollapse,
    LemonDivider,
    LemonDropdown,
    LemonInput,
    LemonInputSelect,
    LemonLabel,
    LemonSegmentedButton,
    LemonSelect,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { MemberSelectMultiple } from 'lib/components/MemberSelectMultiple'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconAdsClick } from 'lib/lemon-ui/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { publicWebhooksHostOrigin } from 'lib/utils/apiHost'
import { createFuse } from 'lib/utils/fuseSearch'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { COHORTS_ONLY_SUPPORT_IN_PICKER_PROPS } from 'scenes/feature-flags/cohortPickerProps'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter/TestAccountFilter'
import { teamLogic } from 'scenes/teamLogic'

import { tagsModel } from '~/models/tagsModel'
import { PropertyFilterType } from '~/types'

import { accountsColumnConfigLogic } from 'products/customer_analytics/frontend/components/Accounts/accountsColumnConfigLogic'
import { ACCOUNT_CUSTOM_PROPERTY_OPERATOR_ALLOWLIST } from 'products/customer_analytics/frontend/components/Accounts/accountsPropertyFilters'
// Side-effect imports: register product-specific trigger types
import 'products/workflows/frontend/Workflows/hogflows/registry/triggers'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowEventFilters, WORKFLOW_OPERATOR_ALLOWLIST } from '../filters/HogFlowFilters'
import { TriggerFrequencyOption, getRegisteredTriggerTypes } from '../registry/triggers/triggerTypeRegistry'
import { HogFlowAction } from '../types'
import { batchTriggerLogic, getAudienceDedupeKey } from './batchTriggerLogic'
import { HogFlowFunctionConfiguration } from './components/HogFlowFunctionConfiguration'
import { RecurringSchedulePicker } from './components/RecurringSchedulePicker'
import { ScheduleStatusBadge } from './components/ScheduleStatusBadge'

type TriggerAction = Extract<HogFlowAction, { type: 'trigger' }>
type EventTriggerConfig = {
    type: 'event'
    filters: {
        events?: any[]
        properties?: any[]
        actions?: any[]
        filter_test_accounts?: boolean
    }
}

type TriggerOptionItem = {
    label: string
    description: string
    value: string
    icon: JSX.Element
    group?: string
    tag?: JSX.Element
}

function getTriggerDisplayType(type: string, config: any): string {
    if (type !== 'event') {
        return type
    }
    const match = getRegisteredTriggerTypes().find((t) => t.matchConfig?.(config))
    return match ? match.value : type
}

function TriggerTypeDropdown({
    items,
    selectedItem,
    onSelect,
}: {
    items: TriggerOptionItem[]
    selectedItem: TriggerOptionItem | undefined
    onSelect: (value: string) => void
}): JSX.Element {
    const [popoverOpen, setPopoverOpen] = useState(false)
    const [search, setSearch] = useState('')

    const filteredItems = useMemo(() => {
        if (!search) {
            return items
        }
        const fuse = createFuse(items, { keys: ['label', 'description'], threshold: 0.3 })
        return fuse.search(search).map((result) => result.item)
    }, [items, search])

    // Group items for display
    const ungrouped = filteredItems.filter((item) => !item.group)
    const grouped: Record<string, TriggerOptionItem[]> = {}
    for (const item of filteredItems) {
        if (item.group) {
            if (!grouped[item.group]) {
                grouped[item.group] = []
            }
            grouped[item.group].push(item)
        }
    }

    return (
        <LemonDropdown
            closeOnClickInside={false}
            visible={popoverOpen}
            onClickOutside={() => {
                setPopoverOpen(false)
                setSearch('')
            }}
            placement="bottom-start"
            matchWidth
            overlay={
                <div className="flex flex-col max-h-120 flex-1 overflow-hidden gap-1">
                    <LemonInput placeholder="Search..." value={search} onChange={setSearch} autoFocus />
                    <ul className="overflow-y-auto flex-1">
                        {ungrouped.map((item) => (
                            <TriggerTypeDropdownItem
                                key={item.value}
                                item={item}
                                selected={item.value === selectedItem?.value}
                                onSelect={() => {
                                    onSelect(item.value)
                                    setPopoverOpen(false)
                                    setSearch('')
                                }}
                            />
                        ))}
                        {Object.entries(grouped).map(([group, groupItems]) => (
                            <li key={group}>
                                <div className="text-xs font-semibold text-muted px-2 pt-2 pb-1">{group}</div>
                                <ul>
                                    {groupItems.map((item) => (
                                        <TriggerTypeDropdownItem
                                            key={item.value}
                                            item={item}
                                            selected={item.value === selectedItem?.value}
                                            onSelect={() => {
                                                onSelect(item.value)
                                                setPopoverOpen(false)
                                                setSearch('')
                                            }}
                                        />
                                    ))}
                                </ul>
                            </li>
                        ))}
                        {filteredItems.length === 0 && (
                            <li className="text-muted text-sm px-2 py-4 text-center">No matching trigger types</li>
                        )}
                    </ul>
                </div>
            }
        >
            <LemonButton type="secondary" fullWidth onClick={() => setPopoverOpen(!popoverOpen)}>
                {selectedItem ? (
                    <span className="flex items-center gap-2">
                        {selectedItem.icon}
                        <span>{selectedItem.label}</span>
                        {selectedItem.tag}
                    </span>
                ) : (
                    'Select trigger type'
                )}
            </LemonButton>
        </LemonDropdown>
    )
}

function TriggerTypeDropdownItem({
    item,
    selected,
    onSelect,
}: {
    item: TriggerOptionItem
    selected: boolean
    onSelect: () => void
}): JSX.Element {
    return (
        <li>
            <LemonButton fullWidth active={selected} onClick={onSelect} icon={item.icon}>
                <div className="flex flex-col my-1">
                    <div className="flex items-baseline font-semibold">
                        <span>{item.label}</span>
                        {item.tag}
                    </div>
                    <p className="text-xs text-muted">{item.description}</p>
                </div>
            </LemonButton>
        </li>
    )
}

export function StepTriggerConfiguration({ node }: { node: Node<TriggerAction> }): JSX.Element {
    const { setWorkflowActionConfig, setWorkflowValue } = useActions(workflowLogic)
    const { actionValidationErrorsById } = useValues(workflowLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const type = node.data.config.type
    const displayType = getTriggerDisplayType(type, node.data.config)
    const validationResult = actionValidationErrorsById[node.id]

    const allTriggerItems = useMemo(() => {
        const items: TriggerOptionItem[] = [
            {
                label: 'Event',
                description: 'Trigger your workflow based on incoming realtime PostHog events',
                value: 'event',
                icon: <IconBolt />,
            },
            {
                label: 'Webhook',
                description: 'Trigger your workflow using an incoming HTTP webhook',
                value: 'webhook',
                icon: <IconWebhooks />,
            },
            ...(type === 'manual'
                ? [
                      {
                          label: 'Manual',
                          description: 'Trigger your workflow manually... with a button!',
                          value: 'manual',
                          icon: <IconButton />,
                      },
                  ]
                : []),
            // The generic "schedule" trigger is hidden from new workflows. It's only offered when the
            // current trigger is already a schedule, so existing workflows still render and can be
            // switched to a different trigger type without crashing.
            ...(type === 'schedule'
                ? [
                      {
                          label: 'Schedule',
                          description: 'Run your workflow on a schedule',
                          value: 'schedule',
                          icon: <IconClock />,
                      },
                  ]
                : []),
            {
                label: 'Tracking pixel',
                description: 'Trigger your workflow using a 1x1 tracking pixel',
                value: 'tracking_pixel',
                icon: <IconAdsClick />,
            },
            {
                label: 'Batch',
                description: 'Trigger your workflow to run for each person in an audience you define.',
                value: 'batch',
                icon: <IconPeople />,
            },
            ...getRegisteredTriggerTypes()
                .filter((t) => !t.featureFlag || featureFlags[t.featureFlag])
                .map((t) => ({
                    label: t.label,
                    description: t.description,
                    value: t.value,
                    icon: t.icon,
                    group: t.group,
                })),
        ]
        return items
    }, [type, featureFlags])

    const selectedItem = allTriggerItems.find((item) => item.value === displayType)

    // Registered trigger types (e.g. data warehouse) can own non-event configs, so resolve the
    // matching definition regardless of config.type and render its ConfigComponent below.
    const registeredMatch = getRegisteredTriggerTypes().find((t) => t.matchConfig?.(node.data.config))

    const handleSelect = (value: string): void => {
        // The frequency hash lives on the workflow, not the trigger config, and hashes are
        // trigger-specific ({person.id} vs event-keyed) — a stale one silently disables masking.
        if (value !== displayType) {
            setWorkflowValue('trigger_masking', null)
        }
        const registered = getRegisteredTriggerTypes().find((t) => t.value === value)
        if (registered) {
            setWorkflowActionConfig(node.id, registered.buildConfig())
        } else if (value === 'event') {
            setWorkflowActionConfig(node.id, { type: 'event', filters: {} })
        } else if (value === 'webhook') {
            setWorkflowActionConfig(node.id, {
                type: 'webhook',
                template_id: 'template-source-webhook',
                inputs: {},
            })
        } else if (value === 'manual') {
            setWorkflowActionConfig(node.id, {
                type: 'manual',
                template_id: 'template-source-webhook',
                inputs: {
                    event: { order: 0, value: '$workflow_triggered' },
                    distinct_id: { order: 1, value: '{request.body.user_id}' },
                    method: { order: 2, value: 'POST' },
                },
            })
        } else if (value === 'schedule') {
            setWorkflowActionConfig(node.id, { type: 'schedule' })
        } else if (value === 'batch') {
            setWorkflowActionConfig(node.id, {
                type: 'batch',
                filters: { properties: [] },
            })
        } else if (value === 'tracking_pixel') {
            setWorkflowActionConfig(node.id, {
                type: 'tracking_pixel',
                template_id: 'template-source-webhook-pixel',
                inputs: {},
            })
        }
    }

    return (
        <div className="flex flex-col items-start w-full gap-2" data-attr="workflow-trigger">
            <span className="flex gap-1">
                <IconBolt className="text-lg" />
                <span className="text-md font-semibold">Trigger type</span>
            </span>
            <span>What causes this workflow to begin?</span>
            <div className="flex items-center gap-2">
                <LemonField.Pure error={validationResult?.errors?.type}>
                    <TriggerTypeDropdown items={allTriggerItems} selectedItem={selectedItem} onSelect={handleSelect} />
                </LemonField.Pure>
                {type === 'schedule' && <ScheduleStatusBadge />}
            </div>
            {registeredMatch?.ConfigComponent ? (
                <>
                    <registeredMatch.ConfigComponent node={node} />
                    {registeredMatch.frequencyOptions ? (
                        <>
                            <LemonDivider />
                            <FrequencySection
                                options={registeredMatch.frequencyOptions}
                                description={registeredMatch.frequencyDescription}
                            />
                        </>
                    ) : null}
                </>
            ) : node.data.config.type === 'event' ? (
                <StepTriggerConfigurationEvents action={node.data} config={node.data.config} />
            ) : node.data.config.type === 'webhook' ? (
                <StepTriggerConfigurationWebhook action={node.data} config={node.data.config} />
            ) : node.data.config.type === 'manual' ? (
                <StepTriggerConfigurationManual />
            ) : node.data.config.type === 'schedule' ? (
                <div className="flex flex-col gap-2 w-full">
                    <p className="text-xs text-muted mb-0">
                        Schedule triggers run without a person or event. If your workflow needs to target specific
                        users, use a batch trigger instead.
                    </p>
                    <LemonField.Pure error={validationResult?.errors?.schedule}>
                        <RecurringSchedulePicker />
                    </LemonField.Pure>
                </div>
            ) : node.data.config.type === 'batch' ? (
                <StepTriggerConfigurationBatch action={node.data} config={node.data.config} />
            ) : node.data.config.type === 'tracking_pixel' ? (
                <StepTriggerConfigurationTrackingPixel action={node.data} config={node.data.config} />
            ) : null}
            <SendingRateLimitSection />
        </div>
    )
}

function StepTriggerConfigurationEvents({
    action,
    config,
}: {
    action: TriggerAction
    config: EventTriggerConfig
}): JSX.Element {
    const { setWorkflowActionConfig } = useActions(workflowLogic)
    const { actionValidationErrorsById } = useValues(workflowLogic)
    const validationResult = actionValidationErrorsById[action.id]
    const filterTestAccounts = config.filters?.filter_test_accounts ?? false

    return (
        <>
            <div className="flex flex-col">
                <p className="mb-0">Choose which events or actions will enter a user into the workflow.</p>
            </div>

            <LemonField.Pure error={validationResult?.errors?.filters}>
                <HogFlowEventFilters
                    filters={config.filters ?? {}}
                    setFilters={(filters) =>
                        setWorkflowActionConfig(action.id, {
                            type: 'event',
                            filters: { ...filters, filter_test_accounts: filterTestAccounts },
                        })
                    }
                    filtersKey={`workflow-trigger-${action.id}`}
                    typeKey="workflow-trigger"
                    buttonCopy="Add trigger event"
                />
            </LemonField.Pure>

            <TestAccountFilter
                filters={{ filter_test_accounts: filterTestAccounts }}
                onChange={({ filter_test_accounts }) =>
                    setWorkflowActionConfig(action.id, {
                        type: 'event',
                        filters: { ...config.filters, filter_test_accounts },
                    })
                }
            />

            <LemonDivider />
            <FrequencySection />
            <LemonDivider />
            <ConversionGoalSection />
            <LemonDivider />
            <ExitConditionSection />
        </>
    )
}

function StepTriggerConfigurationWebhook({
    action,
    config,
}: {
    action: Extract<HogFlowAction, { type: 'trigger' }>
    config: Extract<HogFlowAction['config'], { type: 'webhook' }>
}): JSX.Element {
    const { setWorkflowActionConfig } = useActions(workflowLogic)
    const { workflow, actionValidationErrorsById } = useValues(workflowLogic)
    const validationResult = actionValidationErrorsById[action.id]

    const webhookUrl = workflow.id === 'new' ? null : publicWebhooksHostOrigin() + '/public/webhooks/' + workflow.id

    return (
        <div className="w-full">
            <LemonCollapse
                className="shrink-0"
                defaultActiveKey="instructions"
                panels={[
                    {
                        key: 'instructions',
                        header: 'Usage instructions',
                        className: 'p-3 bg-surface-secondary flex flex-col gap-2',
                        content: (
                            <>
                                {!webhookUrl ? (
                                    <div className="text-xs text-muted italic border rounded p-1 bg-surface-primary">
                                        The webhook URL will be shown here once you save the workflow
                                    </div>
                                ) : (
                                    <CodeSnippet thing="Webhook URL">{webhookUrl}</CodeSnippet>
                                )}

                                <div className="text-sm">
                                    The webhook can be called with any JSON payload. You can then use the configuration
                                    options to parse the <code>request.body</code> or <code>request.headers</code> to
                                    map to the required fields.
                                </div>
                            </>
                        ),
                    },
                ]}
            />
            <HogFlowFunctionConfiguration
                templateId={config.template_id}
                inputs={config.inputs}
                setInputs={(inputs) =>
                    setWorkflowActionConfig(action.id, {
                        type: 'webhook',
                        inputs,
                        template_id: config.template_id,
                        template_uuid: config.template_uuid,
                    })
                }
                errors={validationResult?.errors}
                warnings={validationResult?.warnings}
            />
        </div>
    )
}

function StepTriggerConfigurationManual(): JSX.Element {
    return (
        <>
            <div className="flex gap-1">
                <p className="mb-0">
                    This workflow can be triggered manually via{' '}
                    <Tooltip title="It's up there on the top right ⤴︎">
                        <span className="font-bold cursor-pointer">the trigger button</span>
                    </Tooltip>
                    .
                </p>
            </div>
        </>
    )
}

function StepTriggerAffectedUsers({ actionId, filters }: { actionId: string; filters: any }): JSX.Element | null {
    const { workflow } = useValues(workflowLogic)
    const isAccountAudience = filters?.audience_type === 'accounts'
    // Account audiences carry no person, so email dedup never applies to them.
    const dedupeKey = isAccountAudience ? undefined : getAudienceDedupeKey(workflow)
    const logic = batchTriggerLogic({ id: actionId, filters, dedupeKey })
    const { blastRadiusLoading, blastRadius, blastRadiusError } = useValues(logic)

    if (blastRadiusLoading) {
        return <Spinner className="mt-1" />
    }

    if (blastRadiusError) {
        return (
            <div className="text-warning text-xs flex items-start gap-1 mt-1">
                <IconWarning className="text-base shrink-0 mt-0.5" />
                <div>
                    <div className="font-semibold">
                        Couldn't validate audience size — this batch will likely fail to run.
                    </div>
                    <div>
                        Your filters could not be evaluated against the audience. Review and adjust them before saving,
                        otherwise the batch is likely to error when it executes.
                    </div>
                    <div className="mt-1 text-muted">Details: {blastRadiusError}</div>
                </div>
            </div>
        )
    }

    if (!blastRadius) {
        return null
    }

    const { affected, total, limit } = blastRadius

    if (affected != null && total != null) {
        const exceeded = limit != null && affected > limit
        return (
            <div className="text-muted">
                <div className={exceeded ? 'text-danger font-semibold' : 'text-muted'}>
                    approximately {humanFriendlyNumber(affected)} of {humanFriendlyNumber(total)}{' '}
                    {isAccountAudience ? 'accounts' : 'persons'}.
                </div>
                {exceeded && limit != null && (
                    <div className="text-danger text-xs">
                        Batch size exceeds the limit of {humanFriendlyNumber(limit)}{' '}
                        {isAccountAudience ? 'accounts' : 'users'}. Add filters to narrow your audience. This limit will
                        be loosened in the future.
                    </div>
                )}
            </div>
        )
    }

    return null
}

function BatchScheduleSection(): JSX.Element {
    return (
        <>
            <LemonDivider />
            <LemonLabel showOptional>Schedule</LemonLabel>
            <RecurringSchedulePicker />
        </>
    )
}

type BatchTriggerFilters = Extract<HogFlowAction['config'], { type: 'batch' }>['filters']

function StepTriggerBatchAccountFilters({
    actionId,
    filters,
}: {
    actionId: string
    filters: BatchTriggerFilters
}): JSX.Element {
    const { partialSetWorkflowActionConfig } = useActions(workflowLogic)
    const { tags: tagsAvailable } = useValues(tagsModel)
    const { customPropertyTaxonomicOptions } = useValues(accountsColumnConfigLogic)

    const setFilters = (update: Partial<BatchTriggerFilters>): void => {
        partialSetWorkflowActionConfig(actionId, { filters: { ...filters, ...update } })
    }

    const assignedToUserIds = filters.assigned_to_user_ids ?? []

    return (
        <div className="flex flex-col gap-2">
            <LemonBanner type="info" className="w-full">
                Account audiences run one workflow per account, without a person. Steps that read person properties
                won't fill in. Use the "Get account" step to read account data.
            </LemonBanner>
            <div className="flex flex-wrap gap-2 items-center">
                <LemonInputSelect
                    mode="multiple"
                    allowCustomValues
                    size="small"
                    className="min-w-48"
                    value={filters.tag_names ?? []}
                    options={(tagsAvailable || []).map((tag: string) => ({ key: tag, label: tag }))}
                    onChange={(tag_names) => setFilters({ tag_names })}
                    placeholder="Filter by tags"
                    data-attr="workflows-batch-account-tags-filter"
                />
                <LemonDropdown
                    closeOnClickInside={false}
                    overlay={
                        <div className="p-2 min-w-64 flex flex-col gap-2">
                            <LemonCheckbox
                                checked={!!filters.all_roles_unassigned}
                                onChange={(all_roles_unassigned) => setFilters({ all_roles_unassigned })}
                                label="Unassigned only"
                                data-attr="workflows-batch-account-unassigned-filter"
                            />
                            <LemonDivider className="my-0" />
                            <MemberSelectMultiple
                                idKey="id"
                                value={assignedToUserIds}
                                onChange={(users) => setFilters({ assigned_to_user_ids: users.map((user) => user.id) })}
                            />
                        </div>
                    }
                >
                    <LemonButton type="secondary" size="small" data-attr="workflows-batch-account-assigned-filter">
                        {filters.all_roles_unassigned
                            ? 'Unassigned'
                            : assignedToUserIds.length === 0
                              ? 'Assigned to anyone'
                              : `Assigned to ${assignedToUserIds.length} ${assignedToUserIds.length === 1 ? 'person' : 'people'}`}
                    </LemonButton>
                </LemonDropdown>
            </div>
            {customPropertyTaxonomicOptions.length > 0 && (
                <PropertyFilters
                    pageKey={`workflows-batch-trigger-account-filters-${actionId}`}
                    propertyFilters={filters.properties}
                    addText="Add condition"
                    sendAllKeyUpdates
                    onChange={(properties) => setFilters({ properties })}
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.AccountCustomProperties]}
                    taxonomicFilterOptionsFromProp={{
                        [TaxonomicFilterGroupType.AccountCustomProperties]: customPropertyTaxonomicOptions,
                    }}
                    hasRowOperator={false}
                    operatorAllowlist={ACCOUNT_CUSTOM_PROPERTY_OPERATOR_ALLOWLIST}
                />
            )}
        </div>
    )
}

function StepTriggerConfigurationBatch({
    action,
    config,
}: {
    action: Extract<HogFlowAction, { type: 'trigger' }>
    config: Extract<HogFlowAction['config'], { type: 'batch' }>
}): JSX.Element {
    const { partialSetWorkflowActionConfig } = useActions(workflowLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentTeam } = useValues(teamLogic)

    const accountAudienceAvailable =
        !!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP] &&
        currentTeam?.customer_analytics_config?.account_group_type_index != null
    const isAccountAudience = config.filters.audience_type === 'accounts'

    return (
        <div className="flex flex-col gap-2 my-2 w-full">
            {(accountAudienceAvailable || isAccountAudience) && (
                <LemonSegmentedButton
                    size="small"
                    value={isAccountAudience ? 'accounts' : 'persons'}
                    onChange={(audience_type) =>
                        // Person and account filters are mutually invalid, so switching resets them.
                        partialSetWorkflowActionConfig(action.id, {
                            filters: { audience_type, properties: [] },
                        })
                    }
                    options={[
                        { value: 'persons' as const, label: 'People' },
                        { value: 'accounts' as const, label: 'Accounts' },
                    ]}
                    data-attr="workflows-batch-audience-type"
                />
            )}
            <div>
                <span className="font-semibold">This batch will include</span>{' '}
                <StepTriggerAffectedUsers actionId={action.id} filters={config.filters} />
            </div>
            {isAccountAudience ? (
                <StepTriggerBatchAccountFilters actionId={action.id} filters={config.filters} />
            ) : (
                <div>
                    <PropertyFilters
                        pageKey={`workflows-batch-trigger-property-filters-${action.id}`}
                        propertyFilters={config.filters.properties}
                        addText="Add condition"
                        orFiltering
                        sendAllKeyUpdates
                        allowRelativeDateOptions
                        {...COHORTS_ONLY_SUPPORT_IN_PICKER_PROPS}
                        hideBehavioralCohorts
                        logicalRowDivider
                        onChange={(properties) =>
                            partialSetWorkflowActionConfig(action.id, {
                                filters: {
                                    properties,
                                },
                            })
                        }
                        taxonomicGroupTypes={[
                            TaxonomicFilterGroupType.PersonProperties,
                            TaxonomicFilterGroupType.Cohorts,
                            TaxonomicFilterGroupType.Metadata,
                        ]}
                        taxonomicFilterOptionsFromProp={{
                            [TaxonomicFilterGroupType.Metadata]: [
                                { name: 'distinct_id', propertyFilterType: PropertyFilterType.Person },
                            ],
                        }}
                        hasRowOperator={false}
                        operatorAllowlist={WORKFLOW_OPERATOR_ALLOWLIST}
                    />
                </div>
            )}

            <BatchScheduleSection />
        </div>
    )
}

function StepTriggerConfigurationTrackingPixel({
    action,
    config,
}: {
    action: Extract<HogFlowAction, { type: 'trigger' }>
    config: Extract<HogFlowAction['config'], { type: 'tracking_pixel' }>
}): JSX.Element {
    const { setWorkflowActionConfig } = useActions(workflowLogic)
    const { workflow, actionValidationErrorsById } = useValues(workflowLogic)
    const validationResult = actionValidationErrorsById[action.id]

    const trackingPixelUrl =
        workflow.id !== 'new' ? `${publicWebhooksHostOrigin()}/public/webhooks/${workflow.id}` : null

    const trackingPixelHtml = trackingPixelUrl
        ? `<img
    src="${trackingPixelUrl}.gif"
    width="1" height="1" style="display:none;" alt=""
/>`
        : null

    return (
        <>
            <LemonCollapse
                className="shrink-0"
                defaultActiveKey="instructions"
                panels={[
                    {
                        key: 'instructions',
                        header: 'Usage instructions',
                        className: 'p-3 bg-surface-secondary flex flex-col gap-2',
                        content: (
                            <>
                                {!trackingPixelUrl ? (
                                    <div className="text-xs text-muted italic border rounded p-1 bg-surface-primary">
                                        The tracking pixel URL will be shown here once you save the workflow
                                    </div>
                                ) : (
                                    <CodeSnippet thing="Tracking pixel URL">{trackingPixelUrl}</CodeSnippet>
                                )}

                                <div className="text-sm">
                                    The tracking pixel can be called with a GET request to the URL above. You can embed
                                    it as an image or call it with an HTTP request in any other way.
                                </div>

                                {trackingPixelUrl && (
                                    <CodeSnippet thing="Tracking pixel HTML">{trackingPixelHtml}</CodeSnippet>
                                )}

                                <div>
                                    You can use query parameters to pass in data that you can parse into the event
                                    properties below, or you can hard code the values. This will not create a PostHog
                                    event by default, it will only be used to trigger the workflow.
                                </div>
                            </>
                        ),
                    },
                ]}
            />

            <HogFlowFunctionConfiguration
                templateId={config.template_id}
                inputs={config.inputs}
                setInputs={(inputs) =>
                    setWorkflowActionConfig(action.id, {
                        type: 'tracking_pixel',
                        inputs,
                        template_id: config.template_id,
                        template_uuid: config.template_uuid,
                    })
                }
                errors={validationResult?.errors}
                warnings={validationResult?.warnings}
            />
        </>
    )
}

const MASKING_HASH_PER_PERSON_PER_DAY = "{concat(toString(person.id), '-', formatDateTime(now(), '%Y-%m-%d'))}"
const CALENDAR_DAY_TTL = 24 * 60 * 60

const FREQUENCY_OPTIONS: TriggerFrequencyOption[] = [
    { value: null, label: 'Every time the trigger fires' },
    { value: '{person.id}', label: 'One time' },
    { value: MASKING_HASH_PER_PERSON_PER_DAY, label: 'Once per calendar day', fixedTtl: CALENDAR_DAY_TTL },
]

const TTL_OPTIONS = [
    { value: null, label: 'indefinitely' },
    { value: 5 * 60, label: '5 minutes' },
    { value: 15 * 60, label: '15 minutes' },
    { value: 30 * 60, label: '30 minutes' },
    { value: 60 * 60, label: '1 hour' },
    { value: 2 * 60 * 60, label: '2 hours' },
    { value: 4 * 60 * 60, label: '4 hours' },
    { value: 8 * 60 * 60, label: '8 hours' },
    { value: 12 * 60 * 60, label: '12 hours' },
    { value: 24 * 60 * 60, label: '24 hours' },
    { value: 24 * 60 * 60 * 7, label: '7 days' },
    { value: 24 * 60 * 60 * 30, label: '30 days' },
    { value: 24 * 60 * 60 * 90, label: '90 days' },
    { value: 24 * 60 * 60 * 180, label: '180 days' },
    { value: 24 * 60 * 60 * 365, label: '365 days' },
]

function TTLSelect({
    value,
    onChange,
}: {
    value: number | null | undefined
    onChange: (val: number | null) => void
}): JSX.Element {
    return (
        <div className="flex flex-wrap gap-1 items-center">
            <span>per</span>
            <LemonSelect value={value} onChange={onChange} options={TTL_OPTIONS} />
        </div>
    )
}

function FrequencySection({
    options = FREQUENCY_OPTIONS,
    description = 'Limit how often users can enter this workflow',
}: {
    options?: TriggerFrequencyOption[]
    description?: string
}): JSX.Element {
    const { setWorkflowValue } = useActions(workflowLogic)
    const { workflow } = useValues(workflowLogic)

    const selectedOption = options.find((option) => option.value === (workflow.trigger_masking?.hash ?? null))

    return (
        <div className="flex flex-col w-full py-2">
            <span className="flex gap-1">
                <IconClock className="text-lg" />
                <span className="text-md font-semibold">Frequency</span>
            </span>
            <p>{description}</p>

            <LemonField.Pure>
                <div className="flex flex-wrap gap-1 items-center">
                    <LemonSelect
                        options={options.map(({ value, label }) => ({ value, label }))}
                        value={workflow.trigger_masking?.hash ?? null}
                        onChange={(val) => {
                            const option = options.find((candidate) => candidate.value === val)
                            setWorkflowValue(
                                'trigger_masking',
                                val
                                    ? {
                                          hash: val,
                                          ttl: option?.fixedTtl ?? workflow.trigger_masking?.ttl ?? 60 * 30,
                                      }
                                    : null
                            )
                        }}
                    />
                    {workflow.trigger_masking?.hash && !selectedOption?.fixedTtl ? (
                        <TTLSelect
                            value={workflow.trigger_masking.ttl}
                            onChange={(val) =>
                                setWorkflowValue('trigger_masking', { ...workflow.trigger_masking, ttl: val })
                            }
                        />
                    ) : null}
                </div>
            </LemonField.Pure>
        </div>
    )
}

function ConversionGoalSection(): JSX.Element {
    const { setWorkflowValue } = useActions(workflowLogic)
    const { workflow } = useValues(workflowLogic)

    const conversionEventFilters = workflow.conversion?.events?.[0]?.filters ?? {}

    return (
        <div className="flex flex-col py-2 w-full">
            <span className="flex gap-1 items-center">
                <IconTarget className="text-lg" />
                <span className="text-md font-semibold">Conversion goal (optional)</span>
                <Tooltip title="When a conversion goal is set, each conversion is sent as a billable $workflows_conversion event (with the workflow id and conversion type). You can build insights and cohorts from it, and it counts toward your event usage.">
                    <IconInfo className="text-secondary" />
                </Tooltip>
            </span>
            <p>
                Define what a user must do to be considered converted. All conditions must be met for the user to be
                considered converted.
            </p>

            <div className="flex flex-col gap-4">
                <div className="flex flex-col gap-1 items-start">
                    <LemonLabel>Detect conversion from property changes</LemonLabel>
                    <PropertyFilters
                        buttonText="Add property conversion"
                        buttonClassName="grow-0"
                        propertyFilters={workflow.conversion?.filters ?? []}
                        taxonomicGroupTypes={[
                            TaxonomicFilterGroupType.PersonProperties,
                            TaxonomicFilterGroupType.HogQLExpression,
                        ]}
                        onChange={(filters) => setWorkflowValue('conversion', { ...workflow.conversion, filters })}
                        pageKey="workflow-conversion-properties"
                        hideBehavioralCohorts
                        operatorAllowlist={WORKFLOW_OPERATOR_ALLOWLIST}
                        logicalRowDivider
                    />
                </div>

                <div className="flex flex-col gap-1 items-start w-full">
                    <LemonLabel>Detect conversion from events</LemonLabel>
                    <HogFlowEventFilters
                        filtersKey="workflow-conversion-events"
                        filters={conversionEventFilters}
                        setFilters={(newFilters) =>
                            setWorkflowValue('conversion', {
                                ...workflow.conversion,
                                events: newFilters ? [{ filters: newFilters }] : undefined,
                            })
                        }
                        typeKey="workflow-conversion-event"
                        buttonCopy="Add event"
                    />
                </div>
            </div>
        </div>
    )
}

function SendingRateLimitSection(): JSX.Element | null {
    const { setWorkflowValue } = useActions(workflowLogic)
    const { workflow } = useValues(workflowLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const rateLimit = workflow.email_sending_rate_limit ?? null
    // Mirror the count locally so clearing the field doesn't snap back to the committed value
    // mid-edit; reconcile when the stored value changes externally (toggle, another editor).
    const [displayCount, setDisplayCount] = useState<number | undefined>(rateLimit?.count)
    useEffect(() => {
        setDisplayCount(rateLimit?.count)
    }, [rateLimit?.count])

    // Flag-gated rollout, but a workflow that already carries a limit keeps the section after a
    // flag dial-down so the limit stays visible and removable.
    if (!featureFlags[FEATURE_FLAGS.WORKFLOWS_EMAIL_RATE_LIMIT] && !rateLimit) {
        return null
    }

    const hasEmailAction = workflow.actions.some((action) => action.type === 'function_email')
    // Stay visible while a limit is set even without an email step, so it can still be removed.
    if (!hasEmailAction && !rateLimit) {
        return null
    }

    return (
        <>
            <LemonDivider />
            <div className="flex flex-col w-full py-2 gap-2">
                <span className="flex gap-1 items-center">
                    <IconClock className="text-lg" />
                    <span className="text-md font-semibold">Email sending rate limit (optional)</span>
                    <Tooltip title="Sending a large volume too quickly can hurt deliverability. Emails over the limit are delayed until capacity frees up, not dropped.">
                        <IconInfo className="text-secondary" />
                    </Tooltip>
                </span>
                <p className="mb-0">Spread this workflow's emails out over time instead of sending all at once.</p>
                <LemonCheckbox
                    checked={!!rateLimit}
                    onChange={(checked) =>
                        setWorkflowValue('email_sending_rate_limit', checked ? { count: 100, period: 'minute' } : null)
                    }
                    label="Limit sending rate"
                    data-attr="workflow-email-rate-limit-toggle"
                />
                {rateLimit ? (
                    <div className="flex items-center gap-2">
                        <span>Send at most</span>
                        <LemonInput
                            type="number"
                            size="small"
                            className="w-24"
                            min={1}
                            // Mirror the API's accepted range (min_value=1, max_value=1_000_000) so an
                            // out-of-range entry is clamped here instead of failing the workflow save.
                            max={1_000_000}
                            aria-label="Maximum emails per period"
                            value={displayCount ?? NaN}
                            onChange={(count) => {
                                if (count == null || !Number.isFinite(count)) {
                                    setDisplayCount(undefined)
                                    return
                                }
                                const next = Math.min(1_000_000, Math.max(1, Math.floor(count)))
                                setDisplayCount(next)
                                setWorkflowValue('email_sending_rate_limit', { ...rateLimit, count: next })
                            }}
                            onBlur={() =>
                                displayCount === undefined
                                    ? setDisplayCount(rateLimit.count)
                                    : setWorkflowValue('email_sending_rate_limit', {
                                          ...rateLimit,
                                          count: displayCount,
                                      })
                            }
                            data-attr="workflow-email-rate-limit-count"
                        />
                        <span>emails per</span>
                        <LemonSelect
                            size="small"
                            aria-label="Rate limit period"
                            value={rateLimit.period}
                            options={[
                                { value: 'minute' as const, label: 'minute' },
                                { value: 'hour' as const, label: 'hour' },
                            ]}
                            onChange={(period) =>
                                setWorkflowValue('email_sending_rate_limit', { ...rateLimit, period })
                            }
                            data-attr="workflow-email-rate-limit-period"
                        />
                    </div>
                ) : null}
            </div>
        </>
    )
}

function ExitConditionSection(): JSX.Element {
    const { setWorkflowValue } = useActions(workflowLogic)
    const { workflow } = useValues(workflowLogic)

    return (
        <div className="flex flex-col flex-1 w-full py-2">
            <span className="flex gap-1">
                <IconLeave className="text-lg" />
                <span className="text-md font-semibold">Exit condition</span>
            </span>
            <p>Choose how your users move through the workflow.</p>

            <LemonField.Pure>
                <LemonRadio
                    value={workflow.exit_condition ?? 'exit_only_at_end'}
                    onChange={(value) => setWorkflowValue('exit_condition', value)}
                    options={[
                        {
                            value: 'exit_only_at_end',
                            label: 'Exit only once workflow reaches the end',
                        },
                        {
                            value: 'exit_on_trigger_not_matched',
                            label: 'Exit when trigger filters no longer match',
                        },
                        {
                            value: 'exit_on_conversion',
                            label: 'Exit when conversion goal is met',
                        },
                        {
                            value: 'exit_on_trigger_not_matched_or_conversion',
                            label: 'Exit when trigger filters no longer match, or when conversion goal is met',
                        },
                    ]}
                />
            </LemonField.Pure>
        </div>
    )
}
