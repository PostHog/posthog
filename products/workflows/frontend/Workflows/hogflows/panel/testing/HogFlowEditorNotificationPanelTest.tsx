import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useEffect } from 'react'

import { IconInfo, IconPlayFilled, IconTestTube } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonDivider,
    LemonInput,
    LemonLabel,
    LemonSwitch,
    Popover,
    ProfilePicture,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { isEmail } from 'lib/utils'
import { HogFunctionTestEditor } from 'scenes/hog-functions/configuration/HogFunctionTest'
import { LogsViewerTable } from 'scenes/hog-functions/logs/LogsViewer'
import { asDisplay } from 'scenes/persons/person-utils'

import { PersonType } from '~/types'

import { renderWorkflowLogMessage } from '../../../logs/log-utils'
import { TRIGGER_NODE_ID, workflowLogic } from '../../../workflowLogic'
import { hogFlowEditorLogic } from '../../hogFlowEditorLogic'
import { hogFlowEditorNotificationTestLogic } from './hogFlowEditorNotificationTestLogic'
import { reorderGlobalsForEmailAction } from './hogFlowEditorNotificationTestLogic'

export function EmailActionTestContent(): JSX.Element | null {
    const { workflow, selectedNode } = useValues(hogFlowEditorLogic)
    const { setSelectedNodeId } = useActions(hogFlowEditorLogic)
    const { logicProps } = useValues(workflowLogic)

    const {
        isTestInvocationSubmitting,
        testResult,
        nextActionId,
        testInvocation,
        personSelectorOpen,
        personSearchTerm,
        samplePersons,
        personSearchResults,
        samplePersonsLoading,
        personSearchResultsLoading,
        sampleGlobals,
        sampleGlobalsLoading,
        sampleGlobalsError,
        emailAddressOverride,
    } = useValues(hogFlowEditorNotificationTestLogic(logicProps))
    const {
        submitTestInvocation,
        setTestResult,
        setPersonSelectorOpen,
        setPersonSearchTerm,
        clearPersonSearch,
        loadSamplePersonByDistinctId,
        setEmailAddressOverride,
        setSampleGlobals,
    } = useActions(hogFlowEditorNotificationTestLogic(logicProps))

    const emailInput = emailAddressOverride || sampleGlobals?.person?.properties?.email || ''

    const isLoading = samplePersonsLoading || (sampleGlobalsLoading && !sampleGlobals)

    const handlePersonSelect = (person: PersonType): void => {
        const distinctId = person.distinct_ids?.[0]
        if (distinctId) {
            loadSamplePersonByDistinctId({ distinctId })
            setPersonSelectorOpen(false)
            clearPersonSearch()
        }
    }

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

                <LemonButton type="primary" onClick={() => setSelectedNodeId(TRIGGER_NODE_ID)}>
                    Start testing
                </LemonButton>
            </div>
        )
    }

    return (
        <Form
            logic={hogFlowEditorNotificationTestLogic}
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

                        {nextActionId ? (
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
                        ) : null}
                    </>
                ) : (
                    <>
                        <div className="flex-1" />

                        <LemonButton
                            type="primary"
                            data-attr="test-workflow-panel-new"
                            onClick={() => {
                                const shouldShowConfirmation = !testInvocation?.mock_async_functions

                                if (shouldShowConfirmation) {
                                    LemonDialog.open({
                                        title: 'Confirm email test',
                                        description: `This will send an email to ${emailInput}, do you want to proceed?`,
                                        primaryButton: {
                                            children: 'Send email',
                                            type: 'primary',
                                            onClick: () => {
                                                submitTestInvocation()
                                            },
                                        },
                                        secondaryButton: {
                                            children: 'Cancel',
                                        },
                                    })
                                } else {
                                    submitTestInvocation()
                                }
                            }}
                            loading={isTestInvocationSubmitting}
                            disabledReason={
                                !sampleGlobals
                                    ? 'Must load person to run test'
                                    : !isEmail(emailInput)
                                      ? 'Must enter a valid email address'
                                      : undefined
                            }
                            size="small"
                        >
                            Run test
                        </LemonButton>
                    </>
                )}
            </div>
            <LemonDivider className="my-0" />
            <div className="flex flex-col flex-1 overflow-y-auto">
                <div className="flex-0 bg-surface-secondary p-2">
                    {sampleGlobalsError ? (
                        <div>
                            <LemonBanner type="info" className="mb-2">
                                {sampleGlobalsError}
                            </LemonBanner>
                        </div>
                    ) : null}

                    {/* Select person dropdown at the top */}
                    <div className="mb-4">
                        <LemonLabel>Select person</LemonLabel>
                        <Popover
                            overlay={
                                <div className="p-2 min-w-80">
                                    <LemonInput
                                        type="search"
                                        placeholder="Search by name, email, or distinct ID"
                                        value={personSearchTerm}
                                        onChange={setPersonSearchTerm}
                                        autoFocus
                                        className="mb-2"
                                    />
                                    {personSearchResultsLoading || samplePersonsLoading ? (
                                        <div className="p-4 text-center">
                                            <Spinner />
                                        </div>
                                    ) : (
                                        <div className="max-h-64 overflow-y-auto">
                                            {/* Show sample persons when not searching */}
                                            {!personSearchTerm.trim() && samplePersons.length > 0 ? (
                                                <>
                                                    {samplePersons.map((person: PersonType) => (
                                                        <LemonButton
                                                            key={person.id}
                                                            fullWidth
                                                            size="small"
                                                            onClick={() => handlePersonSelect(person)}
                                                            className="justify-start"
                                                        >
                                                            <ProfilePicture
                                                                name={asDisplay(person)}
                                                                size="sm"
                                                                className="mr-2"
                                                            />
                                                            <div className="flex-1 text-left">
                                                                <div className="font-semibold">{asDisplay(person)}</div>
                                                                {person.properties?.email ? (
                                                                    <div className="text-xs text-muted">
                                                                        {person.properties.email}
                                                                    </div>
                                                                ) : null}
                                                            </div>
                                                        </LemonButton>
                                                    ))}
                                                </>
                                            ) : null}
                                            {/* Show search results */}
                                            {personSearchTerm.trim() && personSearchResults.length === 0 ? (
                                                <div className="p-4 text-center text-muted text-sm">
                                                    No persons found
                                                </div>
                                            ) : (
                                                personSearchResults.map((person: PersonType) => (
                                                    <LemonButton
                                                        key={person.id}
                                                        fullWidth
                                                        size="small"
                                                        onClick={() => handlePersonSelect(person)}
                                                        className="justify-start"
                                                    >
                                                        <ProfilePicture
                                                            name={asDisplay(person)}
                                                            size="sm"
                                                            className="mr-2"
                                                        />
                                                        <div className="flex-1 text-left">
                                                            <div className="font-semibold">{asDisplay(person)}</div>
                                                            {person.properties?.email ? (
                                                                <div className="text-xs text-muted">
                                                                    {person.properties.email}
                                                                </div>
                                                            ) : null}
                                                        </div>
                                                    </LemonButton>
                                                ))
                                            )}
                                        </div>
                                    )}
                                </div>
                            }
                            visible={personSelectorOpen}
                            onClickOutside={() => setPersonSelectorOpen(false)}
                            placement="bottom-start"
                        >
                            <LemonButton
                                type="secondary"
                                onClick={() => setPersonSelectorOpen(!personSelectorOpen)}
                                tooltip="Select a person to load test data"
                                size="small"
                                loading={sampleGlobalsLoading}
                                className="mt-1"
                            >
                                {sampleGlobals?.person?.name ? asDisplay(sampleGlobals.person) : 'Select person'}
                            </LemonButton>
                        </Popover>
                    </div>

                    {/* Person details */}
                    {isLoading ? (
                        <div className="flex gap-2 items-center mb-4">
                            <Spinner />
                            <div className="text-muted">Loading person...</div>
                        </div>
                    ) : sampleGlobals?.person ? (
                        <div className="flex gap-2 items-center mb-4">
                            <ProfilePicture name={asDisplay(sampleGlobals.person)} />
                            <div className="flex-1">
                                <div className="font-semibold mb-2">{sampleGlobals.person.name || 'Sample Person'}</div>
                                <LemonLabel>Email address</LemonLabel>
                                <LemonInput
                                    value={emailInput}
                                    onChange={setEmailAddressOverride}
                                    placeholder="Enter email address"
                                    type="email"
                                    className="mt-1"
                                />
                            </div>
                        </div>
                    ) : null}

                    {/* Person Properties */}
                    {sampleGlobals ? (
                        <>
                            <div className="text-sm mt-2">
                                Here are all the global variables you can use in your workflow:
                            </div>
                            <div className="flex-col gap-2 my-3 max-h-48 overflow-auto">
                                <HogFunctionTestEditor
                                    value={JSON.stringify(reorderGlobalsForEmailAction(sampleGlobals), null, 2)}
                                    onChange={setSampleGlobals}
                                />
                            </div>
                        </>
                    ) : null}
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
                                    renderMessage={(m) => renderWorkflowLogMessage(workflow, m)}
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
