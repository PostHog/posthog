import { IconChevronDown, IconInfo, IconX } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSwitch, LemonTable, Link, ProfilePicture, Tooltip } from '@posthog/lemon-ui'
import { Panel } from '@xyflow/react'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { asDisplay } from 'scenes/persons/person-utils'
import { urls } from 'scenes/urls'

import type { HogFlow } from '../types'
import { hogFlowTestLogic } from './hogFlowTestLogic'

export function HogflowTestPanel({ hogFlow }: { hogFlow: HogFlow }): JSX.Element {
    const { sampleGlobals, isTestInvocationSubmitting, testResult, expanded, canLoadSampleGlobals } = useValues(
        hogFlowTestLogic({ hogFlow })
    )
    const { submitTestInvocation, setTestResult, toggleExpanded, loadSampleGlobals } = useActions(
        hogFlowTestLogic({ hogFlow })
    )

    const inactive = !expanded

    const display = asDisplay(sampleGlobals?.person)
    const url = urls.personByDistinctId(sampleGlobals?.event?.distinct_id || '')

    return (
        <Panel position="bottom-right">
            <Form logic={hogFlowTestLogic} props={{ hogFlow }} formKey="testInvocation" enableFormOnSubmit>
                <div
                    className={
                        expanded
                            ? 'max-w-[600px] max-h-[500px] overflow-y-auto p-4 gap-2 bg-surface-primary rounded-md shadow-md'
                            : ''
                    }
                >
                    <div className="flex items-center justify-between">
                        {inactive ? (
                            <LemonButton
                                data-attr="expand-workflow-test-panel-new"
                                type="primary"
                                className="mb-3"
                                onClick={toggleExpanded}
                                sideIcon={<IconChevronDown className="rotate-180" />}
                            >
                                Test workflow
                            </LemonButton>
                        ) : (
                            <div className="flex w-full justify-between items-center">
                                <span className="text-lg font-semibold nodrag">Test workflow</span>
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
                                    <div className="flex gap-2 items-center">
                                        <LemonButton
                                            type="secondary"
                                            onClick={() => loadSampleGlobals()}
                                            tooltip="Find the last event matching filters, and use it to populate the globals below."
                                            disabledReason={
                                                !canLoadSampleGlobals ? 'Must configure trigger event' : undefined
                                            }
                                        >
                                            Load new event
                                        </LemonButton>

                                        <LemonButton
                                            data-attr="hide-workflow-test-panel-new"
                                            icon={<IconX />}
                                            onClick={() => toggleExpanded()}
                                            tooltip="Hide testing"
                                        />
                                    </div>
                                )}
                            </div>
                        )}
                    </div>

                    {expanded ? (
                        <>
                            {sampleGlobals && (
                                <div className="my-2 gap-2">
                                    {/* Event Information */}
                                    {sampleGlobals.event && (
                                        <div className="bg-surface-secondary rounded p-3">
                                            <div className="flex gap-1 items-center">
                                                {sampleGlobals.person && (
                                                    <Link to={url} className="flex gap-2 items-center">
                                                        <ProfilePicture name={display} />{' '}
                                                        <span className="font-semibold">{display}</span>
                                                    </Link>
                                                )}
                                                <span className="text-muted">performed</span>
                                                <div className="space-y-1 text-md font-semibold">
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
                                                        <div className="text-sm mb-2">Event properties</div>
                                                        <div className="bg-surface-primary rounded p-2 max-h-32 overflow-y-auto">
                                                            <pre className="text-xs text-muted whitespace-pre-wrap">
                                                                {JSON.stringify(
                                                                    sampleGlobals.event.properties,
                                                                    null,
                                                                    2
                                                                )}
                                                            </pre>
                                                        </div>
                                                    </div>
                                                )}
                                        </div>
                                    )}
                                </div>
                            )}

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
                            {!testResult && (
                                <div className="flex flex-col gap-2">
                                    <div className="text-muted text-sm">
                                        Note: Delays will be skipped in test runs to speed up execution.
                                    </div>

                                    <div className="flex gap-4 items-center justify-between">
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
                                                                    When disabled, async functions such as `fetch` will
                                                                    not be called. Instead they will be mocked out and
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
                                            type="primary"
                                            data-attr="test-workflow-panel-new"
                                            onClick={() => submitTestInvocation()}
                                            loading={isTestInvocationSubmitting}
                                        >
                                            Run test
                                        </LemonButton>
                                    </div>
                                </div>
                            )}
                        </>
                    ) : null}
                </div>
            </Form>
        </Panel>
    )
}
