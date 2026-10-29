import { Meta, StoryObj } from '@storybook/react'
import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import type { LogsAlertConfigurationApi } from 'products/logs/frontend/generated/api.schemas'

import { LogsAlertTrigger } from './LogsAlertForm'
import { logsAlertFormLogic } from './logsAlertFormLogic'
import type { LogsAlertGroupBy } from './logsAlertGrouping'
import { LogsAlertRegroupConfirmModal } from './LogsAlertRegroupConfirmModal'
import { LogsAlertSimulation } from './LogsAlertSimulation'

const UNGROUPED_ALERT: LogsAlertConfigurationApi = {
    id: '0192a5b0-0000-7000-8000-0000000000aa',
    name: 'Checkout errors',
    enabled: true,
    filters: { severityLevels: ['error'], serviceNames: ['checkout', 'payments'] },
    threshold_count: 100,
    threshold_operator: 'above',
    window_minutes: 5,
    check_interval_minutes: 5,
    state: 'not_firing',
    evaluation_periods: 1,
    datapoints_to_alarm: 1,
    cooldown_minutes: 0,
    schedule_restriction: null,
    snooze_until: null,
    next_check_at: null,
    last_notified_at: null,
    last_checked_at: null,
    consecutive_failures: 0,
    last_error_message: null,
    state_timeline: [],
    destination_types: [],
    grouping: { mode: 'single', keys: [], max_instances: 100, on_overflow: 'degrade_visible' },
    platform_owned: true,
    first_enabled_at: '2026-10-01T09:00:00Z',
    created_at: '2026-10-01T09:00:00Z',
    created_by: {
        id: 1,
        uuid: '0192a5b0-0000-7000-8000-000000000999',
        distinct_id: 'user-distinct-id',
        first_name: 'Jane',
        email: 'jane@example.com',
        hedgehog_config: null,
    },
    updated_at: null,
}

const GROUPED_ALERT: LogsAlertConfigurationApi = {
    ...UNGROUPED_ALERT,
    id: '0192a5b0-0000-7000-8000-0000000000bb',
    grouping: { mode: 'by_result_labels', keys: ['service_name'], max_instances: 20, on_overflow: 'degrade_visible' },
}

const FIRING_UNGROUPED_ALERT: LogsAlertConfigurationApi = {
    ...UNGROUPED_ALERT,
    id: '0192a5b0-0000-7000-8000-0000000000cc',
    state: 'firing',
}

const meta: Meta = {
    title: 'Products/Logs/Alerting/Group by',
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        mockDate: '2026-10-19',
        // The simulation placeholder draws skeletons as decoration, so they never disappear.
        testOptions: { waitForLoadersToDisappear: false },
    },
}
export default meta

type Story = StoryObj<{}>

function GroupByForm({
    alert,
    width,
    regroupTo,
    maxInstances,
}: {
    alert: LogsAlertConfigurationApi
    width?: string
    regroupTo?: LogsAlertGroupBy
    maxInstances?: number
}): JSX.Element {
    const props = { alert }
    const { canGroup } = useValues(logsAlertFormLogic(props))
    const { setGroupBy, submitAlertForm, setAlertFormValue } = useActions(logsAlertFormLogic(props))

    useEffect(() => {
        if (maxInstances !== undefined) {
            setAlertFormValue('maxInstances', maxInstances)
        }
    }, [maxInstances, setAlertFormValue])

    useEffect(() => {
        if (regroupTo && canGroup) {
            setGroupBy(regroupTo)
            submitAlertForm()
        }
    }, [regroupTo, canGroup, setGroupBy, submitAlertForm])

    return (
        <BindLogic logic={logsAlertFormLogic} props={props}>
            <div className={`space-y-6 ${width}`}>
                <LogsAlertTrigger />
                <LogsAlertSimulation embedded />
            </div>
            <LogsAlertRegroupConfirmModal />
        </BindLogic>
    )
}

export const Ungrouped: Story = {
    render: () => <GroupByForm alert={UNGROUPED_ALERT} width="max-w-2xl" />,
}

export const GroupedByService: Story = {
    render: () => <GroupByForm alert={GROUPED_ALERT} width="max-w-2xl" />,
}

// Pinned to the width a scene has with the nav and the side panel open.
export const GroupedByServiceNarrow: Story = {
    render: () => <GroupByForm alert={GROUPED_ALERT} width="w-[360px]" />,
}

export const GroupLimitOutOfRange: Story = {
    render: () => <GroupByForm alert={GROUPED_ALERT} width="max-w-2xl" maxInstances={0} />,
}

export const GroupFiringAlertConfirmation: Story = {
    render: () => <GroupByForm alert={FIRING_UNGROUPED_ALERT} width="max-w-2xl" regroupTo="service" />,
    parameters: { layout: 'fullscreen', testOptions: { waitForSelector: '.LemonModal' } },
}

export const RegroupConfirmation: Story = {
    render: () => <GroupByForm alert={GROUPED_ALERT} width="max-w-2xl" regroupTo="severity" />,
    parameters: { layout: 'fullscreen', testOptions: { waitForSelector: '.LemonModal' } },
}
