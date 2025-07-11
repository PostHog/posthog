import { IconInfo, IconPlay, IconRedo, IconTestTube, IconX } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDivider,
    LemonLabel,
    LemonSwitch,
    LemonTable,
    Link,
    ProfilePicture,
    Tooltip,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { asDisplay } from 'scenes/persons/person-utils'
import { urls } from 'scenes/urls'

import { hogFlowEditorTestLogic } from './hogFlowEditorTestLogic'
import { campaignLogic } from '../../campaignLogic'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { getHogFlowStep } from '../steps/HogFlowSteps'

export function HogFlowTestPanelNonSelected(): JSX.Element {
    return (
        <div className="p-2 w-120">
            <div className="p-8 text-center rounded border bg-surface-secondary">
                <div className="text-muted">Please select a node...</div>
            </div>
        </div>
    )
}

export function HogFlowEditorTestPanel(): JSX.Element | null {
    const { selectedNode } = useValues(hogFlowEditorLogic)
    const { setSelectedNodeId } = useActions(hogFlowEditorLogic)
    const { logicProps } = useValues(campaignLogic)
    const { sampleGlobals, isTestInvocationSubmitting, testResult, shouldLoadSampleGlobals } = useValues(
        hogFlowEditorTestLogic(logicProps)
    )
    const { submitTestInvocation, setTestResult, loadSampleGlobals } = useActions(hogFlowEditorTestLogic(logicProps))

    const display = asDisplay(sampleGlobals?.person)
    const url = urls.personByDistinctId(sampleGlobals?.event?.distinct_id || '')

    if (!selectedNode) {
        // NOTE: This shouldn't ever happen as the parent checks it
        return null
    }

    const Step = getHogFlowStep(selectedNode.data.type)

    return (
        <Form
            logic={hogFlowEditorTestLogic}
            props={logicProps}
            formKey="testInvocation"
            enableFormOnSubmit
            className="flex overflow-hidden flex-col flex-1 w-180"
        >
            {/* Header */}
            <div className="flex justify-between items-center px-2 my-2 w-full">
                <h3 className="flex gap-1 items-center mb-0 font-semibold">
                    <IconTestTube className="text-lg" />
                    Testing - <span className="text-lg">{Step?.icon}</span> {selectedNode.data.name}
                </h3>
                <div className="flex gap-2 items-center">
                    <LemonButton
                        size="xsmall"
                        icon={<IconX />}
                        onClick={() => setSelectedNodeId(null)}
                        aria-label="close"
                    />
                </div>
            </div>

            <LemonDivider className="my-0" />
            {/* Body */}
            <div className="flex overflow-y-auto flex-col flex-1 gap-2 p-2">
                {/* Event Information */}
                {sampleGlobals?.event && (
                    <div className="p-3 rounded border bg-surface-secondary">
                        <div className="flex flex-wrap gap-1 items-center">
                            {sampleGlobals.person && (
                                <Link to={url} className="flex gap-2 items-center">
                                    <ProfilePicture name={display} /> <span className="font-semibold">{display}</span>
                                </Link>
                            )}
                            <span className="text-muted">performed</span>
                            <div className="space-y-1 font-semibold text-md">{sampleGlobals.event.event}</div>{' '}
                            <div>
                                <TZLabel time={sampleGlobals.event.timestamp} />
                            </div>
                        </div>

                        {/* Event Properties */}
                        {sampleGlobals.event.properties && Object.keys(sampleGlobals.event.properties).length > 0 && (
                            <div className="mt-3">
                                <div className="mb-2 text-sm">Event properties</div>
                                <div className="overflow-auto max-h-32 rounded border bg-surface-primary">
                                    <pre className="p-2 text-xs whitespace-pre-wrap text-muted">
                                        {JSON.stringify(sampleGlobals.event.properties, null, 2)}
                                    </pre>
                                </div>
                            </div>
                        )}
                    </div>
                )}
                {/* Test Results */}
                {testResult && (
                    <div data-attr="test-results" className="flex flex-col gap-2">
                        <h2 className="mb-0">Test results</h2>
                        <LemonBanner
                            type={
                                testResult.status === 'success'
                                    ? 'success'
                                    : testResult.status === 'skipped'
                                    ? 'warning'
                                    : 'error'
                            }
                        >
                            {testResult.status === 'success'
                                ? 'Success'
                                : testResult.status === 'skipped'
                                ? 'Workflow was skipped because the event did not match the filter criteria'
                                : 'Error'}
                        </LemonBanner>

                        <div className="flex flex-col gap-2">
                            <LemonLabel>Test invocation logs</LemonLabel>

                            <LemonTable
                                dataSource={testResult.logs ?? []}
                                columns={[
                                    {
                                        title: 'Timestamp',
                                        key: 'timestamp',
                                        dataIndex: 'timestamp',
                                        render: (timestamp) => <TZLabel time={timestamp as string} />,
                                        width: 0,
                                    },
                                    {
                                        width: 100,
                                        title: 'Level',
                                        key: 'level',
                                        dataIndex: 'level',
                                    },
                                    {
                                        title: 'Message',
                                        key: 'message',
                                        dataIndex: 'message',
                                        render: (message) => <code className="whitespace-pre-wrap">{message}</code>,
                                    },
                                ]}
                                className="ph-no-capture"
                                rowKey="timestamp"
                            />
                        </div>
                    </div>
                )}
            </div>

            <LemonDivider className="my-0" />
            {/* footer */}
            <div className="p-2">
                {testResult ? (
                    <LemonButton
                        type="primary"
                        onClick={() => setTestResult(null)}
                        loading={isTestInvocationSubmitting}
                        data-attr="clear-workflow-test-panel-new-result"
                    >
                        Clear test result
                    </LemonButton>
                ) : (
                    <>
                        <div className="flex flex-col gap-2">
                            <div className="text-sm text-muted">
                                Note: Delays will be logged to indicate when they would have been executed.
                            </div>

                            <div className="flex gap-2 items-center">
                                <LemonField name="mock_async_functions" className="flex-1">
                                    {({ value, onChange }) => (
                                        <LemonSwitch
                                            onChange={(v) => onChange(!v)}
                                            checked={!value}
                                            data-attr="toggle-workflow-test-panel-new-mocking"
                                            label={
                                                <Tooltip
                                                    title={
                                                        <>
                                                            When disabled, message deliveries and other async actions
                                                            will not be called. Instead they will be mocked out and
                                                            logged.
                                                        </>
                                                    }
                                                >
                                                    <span className="flex gap-2">
                                                        Make real HTTP requests
                                                        <IconInfo className="text-lg" />
                                                    </span>
                                                </Tooltip>
                                            }
                                        />
                                    )}
                                </LemonField>

                                <LemonButton
                                    type="secondary"
                                    onClick={() => loadSampleGlobals()}
                                    tooltip="Find the last event matching the trigger event filters, and use it to populate the globals for a test run."
                                    disabledReason={
                                        !shouldLoadSampleGlobals ? 'Must configure trigger event' : undefined
                                    }
                                    icon={<IconRedo />}
                                >
                                    Load new event
                                </LemonButton>

                                <LemonButton
                                    type="primary"
                                    data-attr="test-workflow-panel-new"
                                    onClick={() => submitTestInvocation()}
                                    icon={<IconPlay />}
                                    loading={isTestInvocationSubmitting}
                                    disabledReason={sampleGlobals ? undefined : 'Must load event to run test'}
                                >
                                    Run test
                                </LemonButton>
                            </div>
                        </div>
                    </>
                )}
            </div>
        </Form>
    )
}
