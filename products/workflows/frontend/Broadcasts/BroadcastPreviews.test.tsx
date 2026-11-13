import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { BroadcastEmailPreview } from './BroadcastEmailPreview'
import { broadcastPreviewLogic } from './broadcastPreviewLogic'
import { BroadcastPushPreview } from './BroadcastPushPreview'
import { broadcastTestSendLogic } from './broadcastTestSendLogic'
import { DEFAULT_BROADCAST_EMAIL, broadcastWizardLogic } from './broadcastWizardLogic'

describe('broadcast previews', () => {
    const priorAppContext = window.POSTHOG_APP_CONTEXT

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/persons/': { results: [] },
                '/api/projects/:team_id/persons/': { results: [] },
            },
        })
    })

    afterEach(() => {
        cleanup()
        window.POSTHOG_APP_CONTEXT = priorAppContext
    })

    it.each([
        [AccessControlLevel.Viewer, 'email', 'true'],
        [AccessControlLevel.Editor, 'email', 'false'],
        [AccessControlLevel.Viewer, 'push', 'true'],
        [AccessControlLevel.Editor, 'push', 'false'],
    ])('gives a workflows %s a %s test send button with aria-disabled=%s', (workflowAccess, channel, expected) => {
        window.POSTHOG_APP_CONTEXT = {
            ...priorAppContext,
            resource_access_control: {
                ...priorAppContext?.resource_access_control,
                [AccessControlResourceType.Workflow]: workflowAccess,
            },
        } as AppContext
        initKeaTests()

        render(
            <Provider>
                <BindLogic logic={broadcastWizardLogic} props={{ id: 'new' }}>
                    <BindLogic logic={broadcastPreviewLogic} props={{ id: 'new' }}>
                        <BindLogic logic={broadcastTestSendLogic} props={{ id: 'new' }}>
                            {channel === 'email' ? <BroadcastEmailPreview /> : <BroadcastPushPreview />}
                        </BindLogic>
                    </BindLogic>
                </BindLogic>
            </Provider>
        )

        expect(
            document.querySelector(`[data-attr="broadcast-open-test-${channel === 'email' ? 'email' : 'push'}"]`)
        ).toHaveAttribute('aria-disabled', expected)
    })

    it('shows the modify content button as busy while a new broadcast saves its draft', async () => {
        useMocks({
            post: {
                '/api/projects/:team_id/hog_flows/': () => new Promise(() => {}),
            },
        })
        initKeaTests()
        const wizard = broadcastWizardLogic({ id: 'new' })
        wizard.mount()
        wizard.actions.setEmail({ ...DEFAULT_BROADCAST_EMAIL, html: '<p>Hi</p>' })

        render(
            <Provider>
                <BindLogic logic={broadcastWizardLogic} props={{ id: 'new' }}>
                    <BindLogic logic={broadcastPreviewLogic} props={{ id: 'new' }}>
                        <BindLogic logic={broadcastTestSendLogic} props={{ id: 'new' }}>
                            <BroadcastEmailPreview
                                showTestButton={false}
                                onModifyContent={wizard.actions.editEmailContent}
                            />
                        </BindLogic>
                    </BindLogic>
                </BindLogic>
            </Provider>
        )
        const button = document.querySelector('[data-attr="broadcast-review-modify-content"]') as HTMLElement
        expect(button).toHaveAttribute('aria-disabled', 'false')

        act(() => {
            fireEvent.click(button)
        })

        expect(button).toHaveAttribute('aria-disabled', 'true')
        wizard.unmount()
    })
})
