import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal, LemonSegmentedButton, LemonTextArea, Link } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput'

import { PushIdentityVerificationField } from '../PushIdentityVerificationField'
import { APNSSetupModalLogicProps, apnsSetupModalLogic } from './apnsSetupModalLogic'

export const APNSSetupModal = (props: APNSSetupModalLogicProps): JSX.Element => {
    const { isApnsIntegrationSubmitting, apnsIntegration, signingKeyFileError } = useValues(apnsSetupModalLogic(props))
    const { submitApnsIntegration, setSigningKeyFiles } = useActions(apnsSetupModalLogic(props))

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
                    <div className="flex flex-col gap-2">
                        <LemonField
                            name="signingKey"
                            label="Signing key (.p8)"
                            help="Paste the contents of the key file, or upload the .p8 you downloaded from Apple."
                        >
                            <LemonTextArea
                                placeholder="-----BEGIN PRIVATE KEY-----&#10;...&#10;-----END PRIVATE KEY-----"
                                minRows={4}
                            />
                        </LemonField>
                        <LemonFileInput
                            accept=".p8"
                            multiple={false}
                            onChange={setSigningKeyFiles}
                            callToAction={
                                <LemonButton type="secondary" size="small">
                                    Upload .p8 file
                                </LemonButton>
                            }
                        />
                        {signingKeyFileError && <p className="text-danger text-xs mb-0">{signingKeyFileError}</p>}
                    </div>
                    <LemonField name="keyId" label="Key ID">
                        <LemonInput type="text" placeholder="ABC123DEFG" />
                    </LemonField>
                    <LemonField name="teamId" label="Apple team ID">
                        <LemonInput type="text" placeholder="ABCDE12345" />
                    </LemonField>
                    <LemonField name="bundleId" label="Bundle ID">
                        <LemonInput type="text" placeholder="com.example.app" />
                    </LemonField>
                    <LemonField name="environment" label="Environment">
                        <LemonSegmentedButton
                            options={[
                                { value: 'production', label: 'Production' },
                                { value: 'sandbox', label: 'Sandbox' },
                            ]}
                            fullWidth
                        />
                    </LemonField>
                    <PushIdentityVerificationField mode={apnsIntegration.identityVerification} />
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
