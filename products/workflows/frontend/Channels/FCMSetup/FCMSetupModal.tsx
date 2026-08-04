import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonModal, LemonTextArea, Link } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { PushIdentityVerificationField } from '../PushIdentityVerificationField'
import { FCMSetupModalLogicProps, fcmSetupModalLogic } from './fcmSetupModalLogic'

export const FCMSetupModal = (props: FCMSetupModalLogicProps): JSX.Element => {
    const { isFcmIntegrationSubmitting, fcmIntegration } = useValues(fcmSetupModalLogic(props))
    const { submitFcmIntegration } = useActions(fcmSetupModalLogic(props))

    return (
        <LemonModal
            title={
                <div className="flex items-center gap-2">
                    <span>Configure Firebase Cloud Messaging</span>
                </div>
            }
            onClose={props.onClose}
        >
            <Form logic={fcmSetupModalLogic} formKey="fcmIntegration">
                <div className="gap-4 flex flex-col">
                    <p className="text-secondary">
                        Paste the contents of your Firebase service account key JSON file. You can generate one from the{' '}
                        <Link
                            to="https://console.firebase.google.com/project/_/settings/serviceaccounts/adminsdk"
                            target="_blank"
                        >
                            Firebase Console
                        </Link>{' '}
                        under Project Settings &gt; Service accounts &gt; Generate new private key.
                    </p>
                    <LemonField name="serviceAccountKey" label="Service account key JSON">
                        <LemonTextArea placeholder='{"type": "service_account", ...}' minRows={6} />
                    </LemonField>
                    <PushIdentityVerificationField mode={fcmIntegration.identityVerification} />
                    <div className="flex justify-end">
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isFcmIntegrationSubmitting}
                            onClick={submitFcmIntegration}
                        >
                            Connect
                        </LemonButton>
                    </div>
                </div>
            </Form>
        </LemonModal>
    )
}
