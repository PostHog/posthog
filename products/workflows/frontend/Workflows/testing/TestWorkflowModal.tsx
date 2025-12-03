import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconFlask, IconX } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDivider,
    LemonLabel,
    LemonModal,
    LemonSwitch,
    LemonTable,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'

import { WorkflowSceneLogicProps } from '../workflowSceneLogic'
import { testWorkflowLogic } from './testWorkflowLogic'

export function TestWorkflowModal(props: WorkflowSceneLogicProps): JSX.Element {
    const logic = testWorkflowLogic(props)
    const {
        testModalOpen,
        testResult,
        isTestWorkflowSubmitting,
        testWorkflow,
        testWorkflowErrors,
        exampleEvent,
        exampleEventLoading,
    } = useValues(logic)
    const { setTestModalOpen, clearTestResult, submitTestWorkflow, loadExampleEvent } = useActions(logic)

    return (
        <LemonModal
            title={
                <div className="flex items-center gap-2">
                    <IconFlask className="text-lg" />
                    <span>Test Workflow</span>
                </div>
            }
            isOpen={testModalOpen}
            onClose={() => setTestModalOpen(false)}
            width="70rem"
            footer={
                testResult ? (
                    <div className="flex justify-end gap-2">
                        <LemonButton
                            type="secondary"
                            onClick={clearTestResult}
                        >
                            Test again
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={() => setTestModalOpen(false)}
                        >
                            Close
                        </LemonButton>
                    </div>
                ) : (
                    <div className="flex justify-end gap-2">
                        <LemonButton
                            type="secondary"
                            onClick={() => setTestModalOpen(false)}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={submitTestWorkflow}
                            loading={isTestWorkflowSubmitting}
                            disabledReason={
                                Object.keys(testWorkflowErrors || {}).length > 0
                                    ? 'Please fix the errors in the form'
                                    : undefined
                            }
                        >
                            Run test
                        </LemonButton>
                    </div>
                )
            }
        >
            <Form logic={testWorkflowLogic} props={props} formKey="testWorkflow" enableFormOnSubmit>
                <div className="space-y-4">
                    {testResult ? (
                        <div className="space-y-4">
                            <LemonBanner
                                type={
                                    testResult.status === 'success'
                                        ? 'success'
                                        : testResult.status === 'skipped'
                                          ? 'warning'
                                          : 'error'
                                }
                            >
                                <div className="space-y-2">
                                    <div className="font-semibold">
                                        {testResult.status === 'success'
                                            ? 'Workflow completed successfully'
                                            : testResult.status === 'skipped'
                                              ? 'Workflow was skipped'
                                              : 'Workflow encountered an error'}
                                    </div>
                                    {testResult.finished && (
                                        <div className="text-sm">
                                            Completed {testResult.actionStepCount || 0} action{(testResult.actionStepCount || 0) !== 1 ? 's' : ''}
                                        </div>
                                    )}
                                    {testResult.errors && testResult.errors.length > 0 && (
                                        <div className="text-sm mt-2">
                                            Errors: {testResult.errors.join(', ')}
                                        </div>
                                    )}
                                </div>
                            </LemonBanner>

                            {/* Show variables if any */}
                            {testResult.variables && Object.keys(testResult.variables).length > 0 && (
                                <div>
                                    <LemonLabel>Workflow Variables</LemonLabel>
                                    <p className="text-muted mb-2">
                                        These variables were set during the workflow execution:
                                    </p>
                                    <CodeEditorResizeable
                                        language="json"
                                        value={JSON.stringify(testResult.variables, null, 2)}
                                        height={200}
                                        options={{
                                            readOnly: true,
                                            lineNumbers: 'off',
                                            minimap: { enabled: false },
                                            scrollbar: {
                                                vertical: 'auto',
                                                verticalScrollbarSize: 10,
                                            },
                                            folding: false,
                                        }}
                                    />
                                </div>
                            )}

                            {/* Show action results if any */}
                            {testResult.actionResults && testResult.actionResults.length > 0 && (
                                <div>
                                    <LemonLabel>Action Results</LemonLabel>
                                    <p className="text-muted mb-2">
                                        Results from each action in the workflow:
                                    </p>
                                    <div className="space-y-2">
                                        {testResult.actionResults.map((actionResult: any, index: number) => (
                                            <div key={index} className="p-2 bg-bg-light rounded">
                                                <div className="font-mono text-xs mb-1">
                                                    Action: {actionResult.actionId}
                                                </div>
                                                <CodeEditorResizeable
                                                    language="json"
                                                    value={JSON.stringify(actionResult.result, null, 2)}
                                                    height={100}
                                                    options={{
                                                        readOnly: true,
                                                        lineNumbers: 'off',
                                                        minimap: { enabled: false },
                                                        scrollbar: {
                                                            vertical: 'hidden',
                                                        },
                                                        folding: false,
                                                    }}
                                                />
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* Show logs */}
                            <div>
                                <LemonLabel>Execution Logs</LemonLabel>
                                <p className="text-muted mb-2">
                                    Detailed logs from the workflow execution:
                                </p>
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
                                            render: (level) => (
                                                <span
                                                    className={clsx('font-mono text-xs', {
                                                        'text-danger': level === 'error',
                                                        'text-warning': level === 'warn',
                                                        'text-muted': level === 'debug',
                                                    })}
                                                >
                                                    {level}
                                                </span>
                                            ),
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
                                    pagination={{ pageSize: 100, hideOnSinglePage: true }}
                                />
                            </div>
                        </div>
                    ) : (
                        <div className="space-y-4">
                            <p>
                                Test your workflow by providing example event data and variables. The workflow will be
                                executed with mocked HTTP requests and immediate progression through delay/wait actions.
                            </p>

                            <LemonDivider />

                            {/* Mock async functions toggle */}
                            <LemonField name="mock_async_functions">
                                {({ value, onChange }) => (
                                    <LemonSwitch
                                        onChange={onChange}
                                        checked={value}
                                        label={
                                            <Tooltip
                                                title="When enabled, HTTP requests and other async functions will be mocked and logged instead of making real calls"
                                            >
                                                <span className="flex gap-2 items-center">
                                                    Mock HTTP requests and async functions
                                                </span>
                                            </Tooltip>
                                        }
                                    />
                                )}
                            </LemonField>

                            {/* Event globals */}
                            <LemonField name="globals" showErrorMessage>
                                {({ value, onChange }) => (
                                    <div>
                                        <div className="flex justify-between items-center mb-2">
                                            <LemonLabel>Event Data</LemonLabel>
                                            <LemonButton
                                                type="secondary"
                                                size="small"
                                                onClick={loadExampleEvent}
                                                loading={exampleEventLoading}
                                                icon={exampleEventLoading ? <Spinner /> : undefined}
                                            >
                                                Load example event
                                            </LemonButton>
                                        </div>
                                        <p className="text-muted mb-2">
                                            The event and context data that will trigger the workflow. This should
                                            include event, person, groups, and project information.
                                        </p>
                                        <CodeEditorResizeable
                                            language="json"
                                            value={value}
                                            onChange={onChange}
                                            height={300}
                                            options={{
                                                lineNumbers: 'on',
                                                minimap: { enabled: false },
                                                scrollbar: {
                                                    vertical: 'auto',
                                                    verticalScrollbarSize: 10,
                                                },
                                                folding: true,
                                            }}
                                        />
                                    </div>
                                )}
                            </LemonField>

                            {/* Variables */}
                            <LemonField name="variables" showErrorMessage>
                                {({ value, onChange }) => (
                                    <div>
                                        <LemonLabel>Initial Variables (Optional)</LemonLabel>
                                        <p className="text-muted mb-2">
                                            Set initial values for workflow variables. These will be available
                                            throughout the workflow execution.
                                        </p>
                                        <CodeEditorResizeable
                                            language="json"
                                            value={value}
                                            onChange={onChange}
                                            height={150}
                                            options={{
                                                lineNumbers: 'on',
                                                minimap: { enabled: false },
                                                scrollbar: {
                                                    vertical: 'auto',
                                                    verticalScrollbarSize: 10,
                                                },
                                                folding: false,
                                            }}
                                        />
                                    </div>
                                )}
                            </LemonField>
                        </div>
                    )}
                </div>
            </Form>
        </LemonModal>
    )
}