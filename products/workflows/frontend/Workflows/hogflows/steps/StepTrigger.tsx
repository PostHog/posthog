import { Node } from '@xyflow/react'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useMemo, useState } from 'react'

import {
    IconBolt,
    IconButton,
    IconClock,
    IconLeave,
    IconPeople,
    IconPlusSmall,
    IconTarget,
    IconWebhooks,
} from '@posthog/icons'
import {
    LemonButton,
    LemonCollapse,
    LemonDivider,
    LemonDropdown,
    LemonInput,
    LemonLabel,
    LemonSelect,
    LemonTag,
    Spinner,
    Tooltip,
    lemonToast,
} from '@posthog/lemon-ui'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { IconAdsClick } from 'lib/lemon-ui/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanFriendlyNumber } from 'lib/utils'
import { publicWebhooksHostOrigin } from 'lib/utils/apiHost'
import { createFuse } from 'lib/utils/fuseSearch'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter/TestAccountFilter'

import { PropertyFilterType } from '~/types'

// Side-effect imports: register product-specific trigger types
import 'products/workflows/frontend/Workflows/hogflows/registry/triggers'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowEventFilters, WORKFLOW_OPERATOR_ALLOWLIST } from '../filters/HogFlowFilters'
import { getRegisteredTriggerTypes } from '../registry/triggers/triggerTypeRegistry'
import { HogFlowAction } from '../types'
import { batchTriggerLogic, BLAST_RADIUS_LIMIT } from './batchTriggerLogic'
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
    const { setWorkflowActionConfig } = useActions(workflowLogic)
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
            {
                label: 'Schedule',
                description: 'Run your workflow on a schedule',
                value: 'schedule',
                icon: <IconClock />,
            },
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
                tag: (
                    <LemonTag type="completion" className="ml-1">
                        Beta
                    </LemonTag>
                ),
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

    const handleSelect = (value: string): void => {
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
            {node.data.config.type === 'event' ? (
                (() => {
                    const match = getRegisteredTriggerTypes().find((t) => t.matchConfig?.(node.data.config))
                    if (match?.ConfigComponent) {
                        return <match.ConfigComponent node={node} />
                    }
                    return <StepTriggerConfigurationEvents action={node.data} config={node.data.config} />
                })()
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
    const logic = batchTriggerLogic({ id: actionId, filters })
    const { blastRadiusLoading, blastRadius } = useValues(logic)

    if (blastRadiusLoading) {
        return <Spinner className="mt-1" />
    }

    if (!blastRadius) {
        return null
    }

    const { affected, total } = blastRadius

    if (affected != null && total != null) {
        const exceeded = affected > BLAST_RADIUS_LIMIT
        return (
            <div className="text-muted">
                <div className={exceeded ? 'text-danger font-semibold' : 'text-muted'}>
                    approximately {humanFriendlyNumber(affected)} of {humanFriendlyNumber(total)} persons.
                </div>
                {exceeded && (
                    <div className="text-danger text-xs">
                        Batch size exceeds the limit of {humanFriendlyNumber(BLAST_RADIUS_LIMIT)} users. Add filters to
                        narrow your audience. This limit will be loosened in the future.
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
            <LemonLabel>Schedule</LemonLabel>
            <RecurringSchedulePicker />
        </>
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

    return (
        <div className="flex flex-col gap-2 my-2 w-full">
            <div>
                <span className="font-semibold">This batch will include</span>{' '}
                <StepTriggerAffectedUsers actionId={action.id} filters={config.filters} />
            </div>
            <div>
                <PropertyFilters
                    pageKey={`workflows-batch-trigger-property-filters-${action.id}`}
                    propertyFilters={config.filters.properties}
                    addText="Add condition"
                    orFiltering
                    sendAllKeyUpdates
                    allowRelativeDateOptions
                    exactMatchFeatureFlagCohortOperators
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
                        TaxonomicFilterGroupType.FeatureFlags,
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
            />
        </>
    )
}

const MASKING_HASH_PER_PERSON_PER_DAY = "{concat(toString(person.id), '-', formatDateTime(now(), '%Y-%m-%d'))}"
const CALENDAR_DAY_TTL = 24 * 60 * 60

const FREQUENCY_OPTIONS = [
    { value: null, label: 'Every time the trigger fires' },
    { value: '{person.id}', label: 'One time' },
    { value: MASKING_HASH_PER_PERSON_PER_DAY, label: 'Once per calendar day' },
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

function FrequencySection(): JSX.Element {
    const { setWorkflowValue } = useActions(workflowLogic)
    const { workflow } = useValues(workflowLogic)

    return (
        <div className="flex flex-col w-full py-2">
            <span className="flex gap-1">
                <IconClock className="text-lg" />
                <span className="text-md font-semibold">Frequency</span>
            </span>
            <p>Limit how often users can enter this workflow</p>

            <LemonField.Pure>
                <div className="flex flex-wrap gap-1 items-center">
                    <LemonSelect
                        options={FREQUENCY_OPTIONS}
                        value={workflow.trigger_masking?.hash ?? null}
                        onChange={(val) =>
                            setWorkflowValue(
                                'trigger_masking',
                                val
                                    ? {
                                          hash: val,
                                          ttl:
                                              val === MASKING_HASH_PER_PERSON_PER_DAY
                                                  ? CALENDAR_DAY_TTL
                                                  : (workflow.trigger_masking?.ttl ?? 60 * 30),
                                      }
                                    : null
                            )
                        }
                    />
                    {workflow.trigger_masking?.hash &&
                    workflow.trigger_masking.hash !== MASKING_HASH_PER_PERSON_PER_DAY ? (
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

    return (
        <div className="flex flex-col py-2 w-full">
            <span className="flex gap-1">
                <IconTarget className="text-lg" />
                <span className="text-md font-semibold">Conversion goal (optional)</span>
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

                <div className="flex flex-col gap-1 items-start">
                    <LemonLabel>
                        Detect conversion from events
                        <LemonTag>Coming soon</LemonTag>
                    </LemonLabel>
                    <LemonButton
                        type="secondary"
                        icon={<IconPlusSmall />}
                        onClick={() => {
                            posthog.capture('workflows workflow event conversion clicked')
                            lemonToast.info('Event targeting coming soon!')
                        }}
                    >
                        Add event conversion
                    </LemonButton>
                </div>
            </div>
        </div>
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
