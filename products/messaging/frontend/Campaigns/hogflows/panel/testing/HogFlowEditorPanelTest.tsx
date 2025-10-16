import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useEffect } from 'react'

import { IconInfo, IconPlay, IconPlayFilled, IconRedo, IconTestTube } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCollapse,
    LemonDivider,
    LemonLabel,
    LemonSwitch,
    Link,
    ProfilePicture,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { HogFunctionTestEditor } from 'scenes/hog-functions/configuration/HogFunctionTest'
import { LogsViewerTable } from 'scenes/hog-functions/logs/LogsViewer'
import { asDisplay } from 'scenes/persons/person-utils'
import { urls } from 'scenes/urls'

import { TRIGGER_NODE_ID, campaignLogic } from '../../../campaignLogic'
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

    const {
        sampleGlobals,
        sampleGlobalsLoading,
        isTestInvocationSubmitting,
        testResult,
        shouldLoadSampleGlobals,
        nextActionId,
    } = useValues(hogFlowEditorTestLogic(logicProps))
    const { submitTestInvocation, setTestResult, loadSampleGlobals, setSampleGlobals } = useActions(
        hogFlowEditorTestLogic(logicProps)
    )

    const display = asDisplay(sampleGlobals?.person)
    const url = urls.personByDistinctId(sampleGlobals?.event?.distinct_id || '')

    useEffect(() => {
        setTestResult(null)
    }, [selectedNode?.id, setTestResult])

    if (!selectedNode) {
        return (
            <div className="m-8 text-center flex flex-col gap-2 items-center">
                <h1>
                    <IconTestTube className="mr-2" />
                    Test your workflow
                </h1>

                <p>Step through each action in your workflow and see how it behaves.</p>

                <LemonButton type="primary" onClick={() => setSelectedNodeId(TRIGGER_NODE_ID)} icon={<IconPlay />}>
                    Start testing
                </LemonButton>
            </div>
        )
    }

    return (
        <Form
            logic={hogFlowEditorTestLogic}
            props={logicProps}
            formKey="testInvocation"
            enableFormOnSubmit
            className="flex overflow-hidden flex-col flex-1"
        >
            <div className="flex gap-2 items-center p-2">
                <LemonField name="mock_async_functions" className="flex-1">
                    {({ value, onChange }) => (
                        <LemonSwitch
                            onChange={(v) => onChange(!v)}
                            checked={!value}
                            data-attr="toggle-workflow-test-panel-new-mocking"
                            className="whitespace-nowrap"
                            size="small"
                            bordered
                            label={
                                <Tooltip
                                    title={
                                        <>
                                            When disabled, message deliveries and other async actions will not be
                                            called. Instead they will be mocked out and logged.
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
            <div className="flex flex-col flex-1 overflow-y-auto">
                {/* Event Information */}
                <div className="flex-0">
                    <LemonCollapse
                        embedded
                        panels={[
                            {
                                key: 'event',
                                header: {
                                    children: sampleGlobalsLoading ? (
                                        <>
                                            Loading test event... <Spinner />
                                        </>
                                    ) : (
                                        <>Test event: {sampleGlobals?.event?.event} </>
                                    ),
                                },
                                className: 'bg-surface-secondary',
                                content: (
                                    <div>
                                        <div className="bg-surface-secondary">
                                            <div className="flex gap-2 items-center">
                                                <ProfilePicture name={display} />
                                                <div className="flex-1">
                                                    {sampleGlobals?.person ? (
                                                        <Link to={url} className="flex gap-2 items-center">
                                                            <span className="font-semibold">{display}</span>
                                                        </Link>
                                                    ) : (
                                                        <span className="text-muted">Loading...</span>
                                                    )}{' '}
                                                    <span className="text-muted">performed</span>{' '}
                                                    <span className="space-y-1 font-semibold text-md">
                                                        {sampleGlobals?.event.event}
                                                    </span>{' '}
                                                    {sampleGlobals?.event.timestamp && (
                                                        <TZLabel time={sampleGlobals.event.timestamp} />
                                                    )}
                                                </div>
                                                <LemonButton
                                                    type="secondary"
                                                    onClick={() => loadSampleGlobals()}
                                                    tooltip="Find the last event matching the trigger event filters, and use it to populate the globals for a test run."
                                                    disabledReason={
                                                        !shouldLoadSampleGlobals
                                                            ? 'Must configure trigger event'
                                                            : undefined
                                                    }
                                                    icon={<IconRedo />}
                                                    size="small"
                                                >
                                                    Load new event
                                                </LemonButton>
                                            </div>

                                            {/* Event Properties */}
                                            {sampleGlobals && (
                                                <>
                                                    <div className="text-sm">
                                                        Here are all the global variables you can use in your campaign:
                                                    </div>
                                                    <div className="flex-col gap-2 my-3 max-h-48 overflow-auto">
                                                        <HogFunctionTestEditor
                                                            value={JSON.stringify(sampleGlobals, null, 2)}
                                                            onChange={setSampleGlobals}
                                                        />
                                                    </div>
                                                </>
                                            )}
                                        </div>
                                    </div>
                                ),
                            },
                        ]}
                    />
                </div>
                <LemonDivider className="my-0" />
                <div className="flex flex-col flex-1 gap-2 p-2">
                    <h3 className="mb-0">Test results</h3>
                    {!testResult ? (
                        <div className="text-muted text-sm">No tests run yet</div>
                    ) : (
                        <>
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
                                <LemonLabel>Logs</LemonLabel>

                                <LogsViewerTable
                                    instanceLabel="workflow run"
                                    renderMessage={(m) => renderWorkflowLogMessage(campaign, m)}
                                    dataSource={testResult.logs ?? []}
                                    renderColumns={(columns) => columns.filter((column) => column.key !== 'instanceId')}
                                />
                            </div>
                        </>
                    )}
                </div>
            </div>
        </Form>
    )
}
