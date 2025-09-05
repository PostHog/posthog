import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useEffect } from 'react'

import { IconPlay, IconPlayFilled, IconRedo } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, LemonLabel, Link, ProfilePicture } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LogsViewerTable } from 'scenes/hog-functions/logs/LogsViewer'
import { asDisplay } from 'scenes/persons/person-utils'
import { urls } from 'scenes/urls'

import { campaignLogic } from '../../../campaignLogic'
import { renderWorkflowLogMessage } from '../../../logs/log-utils'
import { hogFlowEditorLogic } from '../../hogFlowEditorLogic'
import { hogFlowEditorTestLogic } from './hogFlowEditorTestLogic'

export function HogFlowTestPanelNonSelected(): JSX.Element {
    return (
        <div className="p-2">
            <div className="p-8 text-center rounded border bg-surface-secondary">
                <div className="text-muted">Please select a node...</div>
            </div>
        </div>
    )
}

export function HogFlowEditorPanelTest(): JSX.Element | null {
    const { campaign, selectedNode } = useValues(hogFlowEditorLogic)
    const { setSelectedNodeId } = useActions(hogFlowEditorLogic)
    const { logicProps } = useValues(campaignLogic)

    const { sampleGlobals, isTestInvocationSubmitting, testResult, shouldLoadSampleGlobals, nextActionId } = useValues(
        hogFlowEditorTestLogic(logicProps)
    )
    const { submitTestInvocation, setTestResult, loadSampleGlobals } = useActions(hogFlowEditorTestLogic(logicProps))

    const display = asDisplay(sampleGlobals?.person)
    const url = urls.personByDistinctId(sampleGlobals?.event?.distinct_id || '')

    useEffect(() => {
        setTestResult(null)
    }, [selectedNode?.id, setTestResult])

    return (
        <Form
            logic={hogFlowEditorTestLogic}
            props={logicProps}
            formKey="testInvocation"
            enableFormOnSubmit
            className="flex overflow-hidden flex-col flex-1"
        >
            <div className="flex gap-2 items-center p-2">
                {testResult ? (
                    <>
                        <div className="flex-1" />
                        <LemonButton
                            type="secondary"
                            onClick={() => setTestResult(null)}
                            loading={isTestInvocationSubmitting}
                            size="small"
                            data-attr="clear-workflow-test-panel-new-result"
                        >
                            Clear test result
                        </LemonButton>

                        {nextActionId && (
                            <LemonButton
                                type="primary"
                                onClick={() => setSelectedNodeId(nextActionId)}
                                icon={<IconPlayFilled />}
                                loading={isTestInvocationSubmitting}
                                size="small"
                                data-attr="continue-workflow-test-panel-new"
                            >
                                Go to next step
                            </LemonButton>
                        )}
                    </>
                ) : (
                    <>
                        <div className="flex-1" />

                        {/* <LemonField name="mock_async_functions" className="flex-1">
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
                                </LemonField> */}

                        <LemonButton
                            type="secondary"
                            onClick={() => loadSampleGlobals()}
                            tooltip="Find the last event matching the trigger event filters, and use it to populate the globals for a test run."
                            disabledReason={!shouldLoadSampleGlobals ? 'Must configure trigger event' : undefined}
                            icon={<IconRedo />}
                            size="small"
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
                            size="small"
                        >
                            Run test
                        </LemonButton>
                    </>
                )}
            </div>
            <LemonDivider className="my-0" />
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
            </div>
            <LemonDivider className="my-0" />
            <div className="flex flex-col flex-1 gap-2 p-2">
                {/* Test Results */}
                {testResult ? (
                    <div data-attr="test-results" className="flex flex-col gap-2">
                        <div className="flex gap-2 justify-between items-center">
                            <h3 className="mb-0">Test results</h3>
                            <LemonButton
                                type="secondary"
                                onClick={() => setTestResult(null)}
                                loading={isTestInvocationSubmitting}
                                size="small"
                                data-attr="clear-workflow-test-panel-new-result"
                            >
                                Clear test result
                            </LemonButton>
                        </div>
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
                                  : 'Error: ' + testResult.errors?.join(', ')}
                        </LemonBanner>

                        <div className="flex flex-col gap-2">
                            <LemonLabel>Test invocation logs</LemonLabel>

                            <LogsViewerTable
                                instanceLabel="workflow run"
                                renderMessage={(m) => renderWorkflowLogMessage(campaign, m)}
                                dataSource={testResult.logs ?? []}
                                renderColumns={(columns) => columns.filter((column) => column.key !== 'instanceId')}
                            />
                        </div>
                    </div>
                ) : (
                    <LemonButton
                        type="primary"
                        data-attr="test-workflow-panel-new"
                        onClick={() => submitTestInvocation()}
                        icon={<IconPlay />}
                        loading={isTestInvocationSubmitting}
                        disabledReason={sampleGlobals ? undefined : 'Must load event to run test'}
                        size="small"
                        fullWidth
                    >
                        Run test
                    </LemonButton>
                )}
            </div>

            <LemonDivider className="my-0" />
            {/* footer */}
        </Form>
    )
}
