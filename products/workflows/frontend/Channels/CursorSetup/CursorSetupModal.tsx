import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal, Link } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { IconCursorAI } from 'lib/lemon-ui/icons'

import { CursorSetupModalLogicProps, cursorSetupModalLogic } from './cursorSetupModalLogic'

export const CursorSetupModal = (props: CursorSetupModalLogicProps): JSX.Element => {
    const { isCursorIntegrationSubmitting } = useValues(cursorSetupModalLogic(props))
    const { submitCursorIntegration } = useActions(cursorSetupModalLogic(props))

    return (
        <LemonModal
            isOpen={props.isOpen}
            title={
                <div className="flex items-center gap-2">
                    <IconCursorAI />
                    <span>Connect Cursor account</span>
                </div>
            }
            onClose={props.onComplete}
        >
            <Form logic={cursorSetupModalLogic} formKey="cursorIntegration">
                <div className="gap-4 flex flex-col">
                    <p className="text-muted text-sm">
                        Generate an API key from your{' '}
                        <Link to="https://cursor.com/settings" target="_blank">
                            Cursor Dashboard
                        </Link>{' '}
                        under Integrations.
                    </p>
                    <LemonField name="apiKey" label="API key">
                        <LemonInput type="password" placeholder="key_xxxxxxxx..." />
                    </LemonField>
                    <div className="flex justify-end">
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isCursorIntegrationSubmitting}
                            onClick={submitCursorIntegration}
                        >
                            Connect
                        </LemonButton>
                    </div>
                </div>
            </Form>
        </LemonModal>
    )
}
