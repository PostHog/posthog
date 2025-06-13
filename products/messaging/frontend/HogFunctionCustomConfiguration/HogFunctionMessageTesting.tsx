import { LemonBanner, LemonButton, LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { hogFunctionConfigurationLogic } from 'scenes/hog-functions/configuration/hogFunctionConfigurationLogic'
import { HogFunctionTestPlaceholder } from 'scenes/hog-functions/configuration/HogFunctionTest'
import { hogFunctionTestLogic } from 'scenes/hog-functions/configuration/hogFunctionTestLogic'

export function HogFunctionMessageTesting(): JSX.Element {
    const { logicProps, configurationChanged } = useValues(hogFunctionConfigurationLogic)
    const { isTestInvocationSubmitting, testResult } = useValues(hogFunctionTestLogic(logicProps))
    const { submitTestInvocation } = useActions(hogFunctionTestLogic(logicProps))

    const getTestMessageGlobals = (email: string): Record<string, any> => {
        return {
            event: {
                event: '$broadcast',
                elements_chain: '',
                timestamp: dayjs().toISOString(),
            },
            person: {
                properties: {
                    email,
                },
            },
        }
    }

    return (
        <HogFunctionTestPlaceholder
            title="Test broadcast"
            description={
                <Form logic={hogFunctionTestLogic} props={logicProps} formKey="testInvocation" enableFormOnSubmit>
                    <p>Test your broadcast message with a sample email before sending it to your users.</p>

                    <div className="flex gap-2 items-end">
                        <LemonField name="globals" className="flex-1">
                            {({ value, onChange }) => (
                                <>
                                    <LemonInput
                                        type="email"
                                        placeholder="test@example.com"
                                        value={value?.person?.properties?.email}
                                        onChange={(value) => {
                                            onChange(
                                                JSON.stringify({
                                                    ...getTestMessageGlobals(value),
                                                })
                                            )
                                        }}
                                    />
                                </>
                            )}
                        </LemonField>

                        <LemonButton
                            type="primary"
                            onClick={submitTestInvocation}
                            loading={isTestInvocationSubmitting}
                            disabledReason={
                                configurationChanged ? 'Save or clear changes to test broadcast' : undefined
                            }
                        >
                            Test broadcast
                        </LemonButton>
                    </div>
                    {testResult && (
                        <LemonBanner
                            type={
                                testResult.status === 'success'
                                    ? 'success'
                                    : testResult.status === 'skipped'
                                    ? 'warning'
                                    : 'error'
                            }
                            className="mt-2"
                        >
                            {testResult.status === 'success'
                                ? 'Success'
                                : testResult.status === 'skipped'
                                ? 'Broadcast was skipped because the event did not match the filter criteria'
                                : 'Error'}
                        </LemonBanner>
                    )}
                </Form>
            }
        />
    )
}
