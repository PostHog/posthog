import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { IconSelfDriving } from 'lib/lemon-ui/icons'

import { registerTriggerType } from 'products/workflows/frontend/Workflows/hogflows/registry/triggers/triggerTypeRegistry'

import { inboxReportAccessLogic } from './inboxReportAccessLogic'
import {
    INBOX_REPORT_PROPERTIES,
    INBOX_REPORT_READY_EVENT,
    isInboxReportReadyTriggerConfig,
} from './inboxReportTriggerConfig'

function useInboxReportTriggerDisabledReason(): string | null {
    return useValues(inboxReportAccessLogic).inboxReportTriggerDisabledReason
}

function StepTriggerConfigurationInboxReportReady(): JSX.Element {
    return (
        <div className="flex flex-col gap-2 w-full">
            <p className="mb-0 text-sm text-muted-alt">
                This workflow runs once for each Inbox report, after its research finishes and the report is ready. Runs
                have no associated person, so person-dependent steps are unavailable.
            </p>
            <p className="mb-0 text-sm text-muted-alt">Use these in later steps:</p>
            <ul className="mb-0 text-sm list-none p-0 flex flex-col gap-1">
                {INBOX_REPORT_PROPERTIES.map(({ key, description }) => (
                    <li key={key}>
                        <code>{`{event.properties.${key}}`}</code>
                        <span className="text-muted-alt"> {description}</span>
                    </li>
                ))}
            </ul>
        </div>
    )
}

registerTriggerType({
    // The tile's own identity, not the stored config type: `internal-event` carries every internal
    // event, so naming the tile after it would make this tile claim all of them.
    value: 'inbox-report-ready',
    label: 'Inbox report ready',
    icon: <IconSelfDriving />,
    description: 'Trigger when an Inbox report finishes research and is ready',
    group: 'Inbox',
    featureFlag: FEATURE_FLAGS.WORKFLOW_INBOX_REPORT_TRIGGER,
    useDisabledReason: useInboxReportTriggerDisabledReason,
    matchConfig: (config) => isInboxReportReadyTriggerConfig(config),
    buildConfig: () => ({
        type: 'internal-event',
        filters: {
            source: 'internal-events',
            events: [{ id: INBOX_REPORT_READY_EVENT, type: 'events' }],
        },
    }),
    ConfigComponent: StepTriggerConfigurationInboxReportReady,
})
