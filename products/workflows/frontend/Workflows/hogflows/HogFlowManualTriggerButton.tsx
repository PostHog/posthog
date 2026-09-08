import { useActions, useValues } from 'kea'

import { IconPlayFilled } from '@posthog/icons'
import { IconChevronDown } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, Popover } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { CyclotronJobInputSchemaType } from '~/types'

import { NextScheduledRun, WorkflowLogicProps, workflowLogic } from '../workflowLogic'
import { hogFlowManualTriggerButtonLogic } from './HogFlowManualTriggerButtonLogic'
import { batchTriggerLogic, getAudienceDedupeKey, hogFlowSendsEmail } from './steps/batchTriggerLogic'

const formatScheduledRun = ({ at, timezone }: NextScheduledRun): string => {
    const local = timezone ? dayjs(at).tz(timezone) : dayjs(at)
    return `${local.format('MMM D, YYYY [at] h:mm A')}${timezone ? ` (${timezone})` : ''}`
}

const TriggerPopover = ({
    setPopoverVisible,
    props,
}: {
    setPopoverVisible: (visible: boolean) => void
    props: WorkflowLogicProps
}): JSX.Element => {
    const logic = hogFlowManualTriggerButtonLogic(props)
    const { workflow, variableValues, inputs } = useValues(logic)
    const { nextScheduledRun } = useValues(workflowLogic(props))
    const { setInput, clearInputs, triggerManualWorkflow, triggerBatchWorkflow } = useActions(logic)

    const isAccountAudience =
        workflow?.trigger?.type === 'batch' && workflow.trigger.filters?.audience_type === 'accounts'

    const { blastRadius, blastRadiusLoading } = useValues(
        batchTriggerLogic({
            id: props.id,
            filters: workflow?.trigger?.type === 'batch' ? workflow?.trigger?.filters : undefined,
            // Account audiences carry no person, so email dedup never applies to them.
            dedupeKey: isAccountAudience ? undefined : getAudienceDedupeKey(workflow),
            sendsEmail: hogFlowSendsEmail(workflow),
        })
    )

    const blastRadiusExceeded =
        workflow?.trigger?.type === 'batch' &&
        blastRadius != null &&
        blastRadius.limit != null &&
        blastRadius.affected > blastRadius.limit

    const blastRadiusSuffix = (): string => {
        if (workflow?.trigger?.type === 'batch') {
            const noun = isAccountAudience ? 'accounts' : 'users'
            return blastRadius ? ` for ${humanFriendlyNumber(blastRadius.affected)} ${noun}` : ' for ...'
        }
        return ''
    }

    const getButtonText = (): string => `Run workflow${blastRadiusSuffix()}`

    const variablesSection =
        !workflow?.variables || workflow.variables.length === 0 ? (
            <>
                <div className="pb-2 border-b">
                    <h3 className="text-sm font-semibold">Configure variables</h3>
                </div>
                <div className="text-muted text-sm">No variables to configure.</div>
            </>
        ) : (
            <>
                <div className="pb-2 border-b">
                    <h3 className="text-sm font-semibold">Configure variables</h3>
                    <p className="text-xs text-muted mt-0.5">Set variable values or leave empty to use defaults</p>
                </div>
                <div className="flex flex-col gap-3">
                    {workflow.variables.map((variable: CyclotronJobInputSchemaType) => {
                        const inputValue = inputs[variable.key]
                        const displayValue = inputValue ?? ''
                        const hasDefault = variable.default !== undefined && variable.default !== ''

                        return (
                            <LemonField.Pure key={variable.key} label={variable.label || variable.key}>
                                {variable.type === 'number' ? (
                                    <LemonInput
                                        type="number"
                                        value={displayValue === '' ? undefined : Number(displayValue)}
                                        placeholder={
                                            hasDefault ? `Default: ${String(variable.default)}` : 'Enter value'
                                        }
                                        onChange={(value: number | undefined) => {
                                            setInput(variable.key, value !== undefined ? String(value) : '')
                                        }}
                                    />
                                ) : (
                                    <LemonInput
                                        type="text"
                                        value={displayValue}
                                        placeholder={
                                            hasDefault ? `Default: ${String(variable.default)}` : 'Enter value'
                                        }
                                        onChange={(value: string) => {
                                            setInput(variable.key, value)
                                        }}
                                    />
                                )}
                            </LemonField.Pure>
                        )
                    })}
                </div>
            </>
        )

    return (
        <div className="flex flex-col gap-4 p-3 min-w-80 max-w-96">
            {nextScheduledRun && (
                <LemonBanner type="warning">
                    This workflow already runs on its own schedule. The next scheduled run is{' '}
                    {formatScheduledRun(nextScheduledRun)}. Running it now is an extra run on top of that.
                </LemonBanner>
            )}
            {variablesSection}
            <div className="flex justify-end border-t pt-3">
                <LemonButton
                    type="primary"
                    status="alt"
                    loading={blastRadiusLoading}
                    disabledReason={
                        blastRadiusExceeded && blastRadius?.limit != null
                            ? `Your audience is above this project's batch limit of ${humanFriendlyNumber(blastRadius.limit)} ${isAccountAudience ? 'accounts' : 'users'}. Add filters to narrow it.${hogFlowSendsEmail(workflow) ? ' The limit rises as the project builds a clean sending history.' : ''}`
                            : undefined
                    }
                    onClick={() => {
                        if (workflow?.trigger?.type === 'batch') {
                            triggerBatchWorkflow(variableValues, workflow?.trigger?.filters || { properties: [] })
                        } else {
                            triggerManualWorkflow(variableValues)
                        }

                        setPopoverVisible(false)
                        clearInputs()
                    }}
                    data-attr="run-workflow-btn"
                    sideIcon={<IconPlayFilled />}
                >
                    {getButtonText()}
                </LemonButton>
            </div>
        </div>
    )
}

export const HogFlowManualTriggerButton = (props: WorkflowLogicProps = {}): JSX.Element => {
    const logic = hogFlowManualTriggerButtonLogic(props)
    const { workflow, hasUnsavedChanges, nextScheduledRun } = useValues(workflowLogic(props))
    const { popoverVisible } = useValues(logic)
    const { setPopoverVisible } = useActions(logic)

    const triggerButton = (
        <LemonButton
            type="primary"
            size="small"
            disabledReason={
                workflow?.status !== 'active'
                    ? 'Must enable workflow to use trigger'
                    : hasUnsavedChanges
                      ? 'Save changes first'
                      : undefined
            }
            sideIcon={<IconChevronDown className={`transition-transform ${popoverVisible ? 'rotate-180' : ''}`} />}
            tooltip={
                nextScheduledRun ? 'Runs the workflow now, on top of its schedule' : 'Runs the workflow now, one time'
            }
            onClick={() => setPopoverVisible(!popoverVisible)}
        >
            Trigger
        </LemonButton>
    )

    return (
        <Popover
            visible={popoverVisible}
            placement="bottom-start"
            onClickOutside={() => setPopoverVisible(false)}
            overlay={<TriggerPopover setPopoverVisible={setPopoverVisible} props={props} />}
        >
            {triggerButton}
        </Popover>
    )
}
