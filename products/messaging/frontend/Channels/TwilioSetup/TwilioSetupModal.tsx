import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { twilioSetupModalLogic, TwilioSetupModalLogicProps } from './twilioSetupModalLogic'
import { IconTwilio } from 'lib/lemon-ui/icons'

export const TwilioSetupModal = (props: TwilioSetupModalLogicProps): JSX.Element => {
    const { isTwilioIntegrationSubmitting } = useValues(twilioSetupModalLogic(props))
    const { submitTwilioIntegration } = useActions(twilioSetupModalLogic(props))

    return (
        <LemonModal
            title={
                <div className="flex items-center gap-2">
                    <IconTwilio />
                    <span>Configure Twilio SMS channel</span>
                </div>
            }
            onClose={props.onComplete}
        >
            <Form logic={twilioSetupModalLogic} formKey="twilioIntegration">
                <div className="gap-4 flex flex-col">
                    <LemonField name="accountSid" label="Account SID">
                        <LemonInput type="text" placeholder="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" />
                    </LemonField>
                    <LemonField name="authToken" label="Auth token">
                        <LemonInput type="password" />
                    </LemonField>
                    <LemonField
                        name="phoneNumber"
                        label="Phone Number"
                        info="Must be an SMS/MMS enabled phone number owned by your Twilio account"
                        help="Must be E.164 format, e.g. +1234567890"
                    >
                        <LemonInput placeholder="+1234567890" />
                    </LemonField>
                    <div className="flex justify-end">
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isTwilioIntegrationSubmitting}
                            onClick={submitTwilioIntegration}
                        >
                            Connect
                        </LemonButton>
                    </div>
                </div>
            </Form>
        </LemonModal>
    )
}
