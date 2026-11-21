import { useActions, useValues } from 'kea'

import { IconSend } from '@posthog/icons'
import { LemonButton, LemonCard, LemonInput, LemonLabel } from '@posthog/lemon-ui'

import { transactionalPushLogic } from './transactionalPushLogic'

export function TransactionalPushTestSend({ id }: { id: string }): JSX.Element {
    const logic = transactionalPushLogic({ id })
    const { testDistinctId, testVariables, savedVariables, lastTestSendLoading, hasChanges } = useValues(logic)
    const { setTestDistinctId, setTestVariable, sendTest } = useActions(logic)
    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-3 p-4">
            <div>
                <div className="font-semibold">Send a test</div>
                <p className="m-0 mt-1 text-sm text-secondary">
                    Sends the published version to every device of one person, like an API call would.
                </p>
            </div>
            <div className="flex flex-col gap-1">
                <LemonLabel htmlFor="transactional-push-test-distinct-id">Distinct ID</LemonLabel>
                <LemonInput
                    id="transactional-push-test-distinct-id"
                    value={testDistinctId}
                    onChange={setTestDistinctId}
                    placeholder="The distinct ID of a person with a registered device"
                    data-attr="transactional-push-test-distinct-id"
                />
            </div>
            {savedVariables.map((name) => (
                <div key={name} className="flex flex-col gap-1">
                    <LemonLabel htmlFor={`transactional-push-test-variable-${name}`}>{name}</LemonLabel>
                    <LemonInput
                        id={`transactional-push-test-variable-${name}`}
                        value={testVariables[name] ?? ''}
                        onChange={(value) => setTestVariable(name, value)}
                        data-attr="transactional-push-test-variable"
                    />
                </div>
            ))}
            <div className="flex justify-end">
                <LemonButton
                    type="secondary"
                    icon={<IconSend />}
                    onClick={sendTest}
                    loading={lastTestSendLoading}
                    disabledReason={
                        !testDistinctId.trim()
                            ? 'Enter a distinct ID'
                            : hasChanges
                              ? 'Publish your changes first, because a test sends the published version'
                              : undefined
                    }
                    data-attr="transactional-push-send-test"
                >
                    Send test
                </LemonButton>
            </div>
        </LemonCard>
    )
}
