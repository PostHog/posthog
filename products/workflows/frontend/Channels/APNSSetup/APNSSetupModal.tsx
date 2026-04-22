import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal, LemonTextArea, Link } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { APNSSetupModalLogicProps, apnsSetupModalLogic } from './apnsSetupModalLogic'

export const APNSSetupModal = (props: APNSSetupModalLogicProps): JSX.Element => {
    const { isApnsIntegrationSubmitting } = useValues(apnsSetupModalLogic(props))
    const { submitApnsIntegration } = useActions(apnsSetupModalLogic(props))

    return (
        <LemonModal
            title={
                <div className="flex items-center gap-2">
                    <span>Configure Apple Push Notification Service</span>
                </div>
            }
            onClose={props.onClose}
        >
            <Form logic={apnsSetupModalLogic} formKey="apnsIntegration">
                <div className="gap-4 flex flex-col">
                    <p className="text-secondary">
                        You can find these values in your{' '}
                        <Link to="https://developer.apple.com/account/resources/authkeys/list" target="_blank">
                            Apple Developer account
                        </Link>{' '}
                        under Certificates, Identifiers & Profiles &gt; Keys.
                    </p>
                    <LemonField name="signingKey" label="Signing key (.p8)">
                        <LemonTextArea
                            placeholder="-----BEGIN PRIVATE KEY-----&#10;...&#10;-----END PRIVATE KEY-----"
                            minRows={4}
                        />
                    </LemonField>
                    <LemonField name="keyId" label="Key ID">
                        <LemonInput type="text" placeholder="ABC123DEFG" />
                    </LemonField>
                    <LemonField name="teamId" label="Apple team ID">
                        <LemonInput type="text" placeholder="ABCDE12345" />
                    </LemonField>
                    <LemonField name="bundleId" label="Bundle ID">
                        <LemonInput type="text" placeholder="com.example.app" />
                    </LemonField>
                    <div className="flex justify-end">
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isApnsIntegrationSubmitting}
                            onClick={submitApnsIntegration}
                        >
                            Connect
                        </LemonButton>
                    </div>
                </div>
            </Form>
        </LemonModal>
    )
}
