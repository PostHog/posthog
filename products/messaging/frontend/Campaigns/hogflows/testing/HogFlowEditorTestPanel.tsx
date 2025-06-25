import { IconChevronDown, IconInfo, IconPlay, IconTestTube, IconX } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDivider,
    LemonSwitch,
    LemonTable,
    Link,
    ProfilePicture,
    Tooltip,
} from '@posthog/lemon-ui'
import { Panel } from '@xyflow/react'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { asDisplay } from 'scenes/persons/person-utils'
import { urls } from 'scenes/urls'

import { hogFlowEditorTestLogic } from './hogFlowEditorTestLogic'
import { campaignLogic } from '../../campaignLogic'

export function HogFlowEditorTestPanel(): JSX.Element {
    const { logicProps } = useValues(campaignLogic)
    const { sampleGlobals, isTestInvocationSubmitting, testResult, expanded, canLoadSampleGlobals } = useValues(
        hogFlowEditorTestLogic(logicProps)
    )
    const { submitTestInvocation, setTestResult, toggleExpanded, loadSampleGlobals } = useActions(
        hogFlowEditorTestLogic(logicProps)
    )

    const inactive = !expanded

    if (inactive) {
        return (
            <Panel position="bottom-right">
                <LemonButton
                    data-attr="expand-workflow-test-panel-new"
                    type="tertiary"
                    className="rounded border transition-all cursor-pointer bg-surface-primary"
                    onClick={toggleExpanded}
                    icon={<IconTestTube />}
                    sideIcon={<IconChevronDown className="rotate-180" />}
                >
                    Test workflow
                </LemonButton>
            </Panel>
        )
    }

    const display = asDisplay(sampleGlobals?.person)
    const url = urls.personByDistinctId(sampleGlobals?.event?.distinct_id || '')

    return (
        <Panel position="bottom-right">
            <Form logic={hogFlowEditorTestLogic} props={logicProps} formKey="testInvocation" enableFormOnSubmit>
                <div className="max-w-[600px] max-h-[500px] overflow-y-auto gap-2 bg-surface-primary rounded-md shadow-md">
                    {/* Header */}
                    <div className="flex justify-between items-center px-2 my-2 w-full">
                        <h3 className="flex gap-1 items-center mb-0 font-semibold">
                            <IconTestTube className="text-lg" />
                            Test workflow
                        </h3>
                        <div className="flex gap-2 items-center">
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
                                <LemonButton
                                    type="secondary"
                                    onClick={() => loadSampleGlobals()}
                                    tooltip="Find the last event matching the trigger event filters, and use it to populate the globals for a test run."
                                    disabledReason={!canLoadSampleGlobals ? 'Must configure trigger event' : undefined}
                                >
                                    Load new event
                                </LemonButton>
                            )}
                            <LemonButton
                                size="xsmall"
                                icon={<IconX />}
                                onClick={() => toggleExpanded()}
                                aria-label="close"
                            />
                        </div>
                    </div>

                    <LemonDivider className="my-0" />
                    {/* Body */}
                    <div className="p-2">
                        {/* Event Information */}
                        {sampleGlobals && (
                            <div className="gap-2 my-2">
                                {/* Event Information */}
                                {sampleGlobals.event && (
                                    <div className="p-3 rounded bg-surface-secondary">
                                        <div className="flex gap-1 items-center">
                                            {sampleGlobals.person && (
                                                <Link to={url} className="flex gap-2 items-center">
                                                    <ProfilePicture name={display} />{' '}
                                                    <span className="font-semibold">{display}</span>
                                                </Link>
                                            )}
                                            <span className="text-muted">performed</span>
                                            <div className="space-y-1 font-semibold text-md">
                                                {sampleGlobals.event.event}
                                            </div>{' '}
                                            <div>
                                                <TZLabel time={sampleGlobals.event.timestamp} />
                                            </div>
                                        </div>

                                        {/* Event Properties */}
                                        {sampleGlobals.event.properties &&
                                            Object.keys(sampleGlobals.event.properties).length > 0 && (
                                                <div className="mt-3">
                                                    <div className="mb-2 text-sm">Event properties</div>
                                                    <div className="overflow-y-auto p-2 max-h-32 rounded bg-surface-primary">
                                                        <pre className="text-xs whitespace-pre-wrap text-muted">
                                                            {JSON.stringify(sampleGlobals.event.properties, null, 2)}
                                                        </pre>
                                                    </div>
                                                </div>
                                            )}
                                    </div>
                                )}
                            </div>
                        )}
                        {/* Test Results */}
                        {testResult && (
                            <div className="gap-2" data-attr="test-results">
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

                                <div className="gap-2">
                                    <div className="font-semibold">Test invocation logs</div>

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
                                                render: (message) => (
                                                    <code className="whitespace-pre-wrap">{message}</code>
                                                ),
                                            },
                                        ]}
                                        className="ph-no-capture"
                                        rowKey="timestamp"
                                        pagination={{ pageSize: 200, hideOnSinglePage: true }}
                                    />
                                </div>
                            </div>
                        )}
                        {/* Test Kickoff */}
                        {!testResult && (
                            <div className="flex flex-col gap-2">
                                <div className="text-sm text-muted">
                                    Note: Delays will be skipped in test runs to speed up execution.
                                </div>

                                <div className="flex gap-4 justify-between items-center">
                                    <LemonField name="mock_async_functions">
                                        {({ value, onChange }) => (
                                            <LemonSwitch
                                                onChange={(v) => onChange(!v)}
                                                checked={!value}
                                                data-attr="toggle-workflow-test-panel-new-mocking"
                                                label={
                                                    <Tooltip
                                                        title={
                                                            <>
                                                                When disabled, message deliveries and other async
                                                                actions will not be called. Instead they will be mocked
                                                                out and logged.
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
                        )}
                    </div>
                </div>
            </Form>
        </Panel>
    )
}
