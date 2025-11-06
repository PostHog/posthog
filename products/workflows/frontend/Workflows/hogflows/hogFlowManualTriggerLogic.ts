import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { workflowLogic } from '../workflowLogic'
import { WorkflowSceneLogicProps } from '../workflowSceneLogic'

export const hogFlowManualTriggerLogic = kea([
    path(['products', 'workflows', 'frontend', 'Workflows', 'hogflows', 'hogFlowManualTriggerLogic']),
    props({ id: 'new' } as WorkflowSceneLogicProps),
    key((props) => props.id || 'new'),
    connect(() => ({
        values: [userLogic, ['user'], teamLogic, ['timezone'], workflowLogic, ['workflow', 'workflowChanged']],
    })),
    actions({
        togglePopoverVisible: true,
        toggleUseDefaults: true,
        setInput: true,
        toggleScheduleEnabled: true,
        setScheduledDateTime: (date: any) => ({ date }),
    }),
    reducers(() => ({
        manualTriggerPopoverVisible: [
            false as boolean,
            {
                togglePopoverVisible: (state) => !state,
            },
        ],
        inputs: [
            {} as Record<string, string>,
            {
                setInput: (state: Record<string, string>, { key, value }: any) => ({ ...state, [key]: value }),
            },
        ],
        useDefaults: [
            true as boolean,
            {
                toggleUseDefaults: (state) => !state,
            },
        ],
        scheduleEnabled: [
            false as boolean,
            {
                toggleScheduleEnabled: (state) => !state,
            },
        ],
        scheduledDateTime: [
            null as dayjs.Dayjs | null,
            {
                setScheduledDateTime: (_: any, { date }: any) => date,
            },
        ],
    })),
    selectors({
        variableValues: [
            (s) => [s.workflow, s.useDefaults, s.inputs],
            (workflow: any, useDefaults: boolean, inputs: Record<string, string>): Record<string, string> => {
                if (!workflow?.variables) {
                    return {}
                }
                if (useDefaults) {
                    return Object.fromEntries(workflow.variables.map((v: any) => [v.key, v.default ?? '']))
                }
                return Object.fromEntries(workflow.variables.map((v: any) => [v.key, inputs[v.key] ?? v.default ?? '']))
            },
        ],
        scheduleDisabledReason: [
            (s) => [s.scheduleEnabled, s.scheduledDateTime],
            (enabled: boolean, date: dayjs.Dayjs | null) =>
                enabled && !date ? 'Select a date and time for scheduling' : undefined,
        ],
    }),
    listeners(({ values, actions }) => ({
        toggleScheduleEnabled: () => {
            if (!values.scheduleEnabled) {
                actions.setScheduledDateTime(null)
            }
        },
    })),
])
