import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { userLogic } from 'scenes/userLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { HogFlowApi } from '../generated/api.schemas'
import { HogflowTestResult } from '../Workflows/hogflows/steps/types'
import { broadcastPreviewLogic } from './broadcastPreviewLogic'
import { broadcastTestSendLogic } from './broadcastTestSendLogic'
import { DEFAULT_BROADCAST_EMAIL, broadcastWizardLogic } from './broadcastWizardLogic'

const READY_EMAIL = {
    ...DEFAULT_BROADCAST_EMAIL,
    from: { integrationId: 1, email: 'team@example.com' },
    subject: 'Hello {{ person.properties.name }}',
    html: '<p>Hi</p>',
    cc: 'boss@example.com',
    bcc: 'audit@example.com',
}
const READY_PUSH = { channels: [7], title: 'New release', body: 'Open the app' }
const SAVED_PUSH_INPUTS = { title: { value: 'Old', templating: 'hog' }, data: { value: { screen: 'home' } } }
const NO_DEVICE = 'No device took the notification. Check that this person has push turned on in your app.'
const PREVIEW_PERSON = { id: 'person-1', displayName: 'Ada', properties: { email: 'ada@example.com', name: 'Ada' } }

const log = (message: string, level = 'info'): any => ({ level, timestamp: '2026-01-01T00:00:00Z', message })
const result = (partial: Partial<HogflowTestResult>): HogflowTestResult => ({
    status: 'success',
    nextActionId: null,
    ...partial,
})

describe('broadcastTestSendLogic', () => {
    let wizard: ReturnType<typeof broadcastWizardLogic.build>
    let logic: ReturnType<typeof broadcastTestSendLogic.build>
    let send: jest.SpyInstance
    let toasts: Record<'success' | 'warning' | 'error', jest.SpyInstance>

    beforeEach(() => {
        useMocks({
            get: { '/api/projects/:team_id/integrations/': { results: [], count: 0 } },
            post: {
                '/api/projects/:team_id/hog_flows/user_blast_radius/': () => [200, { affected: 0, total: 0 }],
                '/api/environments/:team_id/query/': () => [200, { results: [] }],
            },
        })
        initKeaTests()
        send = jest.spyOn(api.hogFlows, 'createTestInvocation').mockResolvedValue(result({}))
        toasts = {
            success: jest.spyOn(lemonToast, 'success').mockReturnValue('' as any),
            warning: jest.spyOn(lemonToast, 'warning').mockReturnValue('' as any),
            error: jest.spyOn(lemonToast, 'error').mockReturnValue('' as any),
        }
        wizard = broadcastWizardLogic({ id: 'new' })
        wizard.mount()
        logic = broadcastTestSendLogic({ id: 'new' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        wizard.unmount()
        jest.restoreAllMocks()
        resumeKeaLoadersErrors()
    })

    const sendTest = async (): Promise<void> => {
        await expectLogic(logic, () => logic.actions.sendTestEmail())
            .toDispatchActions(['sendTestEmailSuccess'])
            .toFinishAllListeners()
    }

    const usePush = async (): Promise<void> => {
        await expectLogic(wizard).toFinishAllListeners()
        wizard.actions.setChannel('push')
        wizard.actions.setPush(READY_PUSH)
    }

    it('sends one email to the typed address only, with the real step name and the preview person', async () => {
        wizard.actions.loadBroadcastSuccess({
            actions: [{ id: 'email_node', name: 'Launch email', type: 'function_email', config: {} }],
        } as unknown as HogFlowApi)
        wizard.actions.setName('Launch')
        wizard.actions.setEmail(READY_EMAIL)
        wizard.actions.setEmailSettings({ utmTagsEnabled: true, utmParams: { utm_source: 'newsletter' } })
        broadcastPreviewLogic({ id: 'new' }).actions.loadPersonsSuccess([PREVIEW_PERSON])
        logic.actions.setRecipientEmail('reviewer@example.com')

        await sendTest()

        expect(send).toHaveBeenCalledTimes(1)
        const [id, payload] = send.mock.calls[0]
        expect(id).toBe('new')
        expect(payload).toMatchObject({ mock_async_functions: false, current_action_id: 'send_test_email' })
        expect(payload.configuration.name).toBe('Launch')
        const emailAction = payload.configuration.actions.find((action: any) => action.id === 'send_test_email')
        expect(emailAction.config.utm_tags_enabled).toBe(true)
        expect(emailAction.config.utm_params).toEqual({ utm_content: 'Launch email', utm_source: 'newsletter' })
        expect(emailAction.config.inputs.email).toEqual({
            value: { ...READY_EMAIL, to: { email: 'reviewer@example.com', name: '' }, cc: '', bcc: '' },
            templating: 'liquid',
        })
        expect(payload.configuration.edges).toEqual([
            { from: 'trigger_node', to: 'send_test_email', type: 'continue' },
            { from: 'send_test_email', to: 'exit_node', type: 'continue' },
        ])
        expect(payload.globals.person).toMatchObject({ id: 'person-1', name: 'Ada', properties: { name: 'Ada' } })
    })

    it('sends one push to the trimmed distinct ID, keeping the saved push inputs', async () => {
        wizard.actions.loadBroadcastSuccess({
            actions: [{ id: 'push_node', type: 'function_push', config: { inputs: SAVED_PUSH_INPUTS } }],
        } as unknown as HogFlowApi)
        await usePush()
        wizard.actions.setName('')
        broadcastPreviewLogic({ id: 'new' }).actions.loadPersonsSuccess([PREVIEW_PERSON])
        logic.actions.setRecipientDistinctId('  user-{{ 1 }}  ')

        await sendTest()

        expect(send).toHaveBeenCalledTimes(1)
        const [, payload] = send.mock.calls[0]
        expect(payload).toMatchObject({ mock_async_functions: false, current_action_id: 'send_test_push' })
        expect(payload.configuration.name).toBe('Test broadcast')
        const pushAction = payload.configuration.actions.find((action: any) => action.id === 'send_test_push')
        expect(pushAction.config.template_id).toBe('template-native-push')
        expect(pushAction.config.inputs).toMatchObject({
            channels: { value: [7] },
            title: { value: 'New release', templating: 'hog' },
            body: { value: 'Open the app', templating: 'liquid' },
            data: SAVED_PUSH_INPUTS.data,
            distinctId: { value: '{% raw %}user-{{ 1 }}{% endraw %}', templating: 'liquid' },
        })
        expect(payload.globals.person).toMatchObject({ id: 'person-1', name: 'Ada', properties: { name: 'Ada' } })
    })

    it.each([
        { case: 'no sender', email: { from: {} }, to: 'a@example.com', reason: 'Choose an email sender first' },
        { case: 'no subject', email: { subject: '' }, to: 'a@example.com', reason: 'Add a subject first' },
        { case: 'no content', email: { html: '', text: '' }, to: 'a@example.com', reason: 'Add email content first' },
        { case: 'text only', email: { html: '', text: 'Hi' }, to: 'a@example.com', reason: undefined },
        { case: 'no address', email: {}, to: '', reason: 'Enter a valid email address' },
        { case: 'a malformed address', email: {}, to: 'not-an-email', reason: 'Enter a valid email address' },
        { case: 'everything set', email: {}, to: 'a@example.com', reason: undefined },
    ])('blocks an email test with $case', ({ email, to, reason }) => {
        wizard.actions.setEmail({ ...READY_EMAIL, ...email })
        logic.actions.setRecipientEmail(to)

        expect(logic.values.sendDisabledReason).toBe(reason)
    })

    it.each([
        { case: 'no channel', push: { channels: [] }, to: 'me', reason: 'Choose a push channel first' },
        { case: 'a blank title', push: { title: '  ' }, to: 'me', reason: 'Add a notification title first' },
        { case: 'an endraw', push: {}, to: '{% endraw', reason: 'This distinct ID contains text that cannot be sent' },
        { case: 'a blank distinct ID', push: {}, to: '   ', reason: 'Enter a distinct ID' },
        { case: 'everything set', push: {}, to: 'me', reason: undefined },
    ])('blocks a push test with $case', async ({ push, to, reason }) => {
        await usePush()
        wizard.actions.setPush({ ...READY_PUSH, ...push })
        logic.actions.setRecipientDistinctId(to)

        expect(logic.values.sendDisabledReason).toBe(reason)
    })

    it.each([
        {
            case: 'an email delivered',
            channel: 'email',
            response: result({}),
            toast: ['success', 'Test email sent to reviewer@example.com'],
            vouchedFor: 'reviewer@example.com',
        },
        {
            case: 'an email the provider declined',
            channel: 'email',
            response: result({ emailSendResult: { status: 'skipped', reason: 'Opted out' } }),
            toast: ['warning', 'Nothing was sent, see why below', 'Opted out'],
            vouchedFor: null,
        },
        {
            case: 'an email step that was skipped',
            channel: 'email',
            response: result({ status: 'skipped' }),
            toast: ['warning', 'The email step was skipped, so nothing was sent'],
            vouchedFor: null,
        },
        {
            case: 'an email run that errored',
            channel: 'email',
            response: result({ status: 'error', errors: ['boom'] }),
            toast: ['error', 'Could not send the test email'],
            vouchedFor: null,
        },
        {
            case: 'a push delivered',
            channel: 'push',
            response: result({ logs: [log('Push notification accepted by FCM for 1 of 1 device(s).')] }),
            toast: ['success', "Test notification sent to me's devices"],
            vouchedFor: 'me',
        },
        {
            case: 'a push no device took',
            channel: 'push',
            response: result({ logs: [] }),
            toast: ['warning', 'Nothing was sent, see why below', NO_DEVICE],
            vouchedFor: null,
        },
        {
            case: 'a push one app failed',
            channel: 'push',
            response: result({
                logs: [log('Push notification accepted by FCM for 1 of 1 device(s).'), log('APNs: BadDeviceToken')],
            }),
            toast: ['warning', 'Sent through some apps only, see the errors below', 'APNs: BadDeviceToken'],
            vouchedFor: 'me',
        },
        {
            case: 'a push run that errored',
            channel: 'push',
            response: result({ status: 'error', errors: ['boom'] }),
            toast: ['error', 'Could not send the test notification'],
            vouchedFor: null,
        },
        {
            case: 'a push step that was skipped',
            channel: 'push',
            response: result({ status: 'skipped' }),
            toast: ['warning', 'The push step was skipped, so nothing was sent'],
            vouchedFor: null,
        },
    ])('reports $case', async ({ channel, response, toast: [kind, message, detail], vouchedFor }) => {
        if (channel === 'push') {
            await usePush()
        } else {
            wizard.actions.setEmail(READY_EMAIL)
        }
        logic.actions.setModalOpen(true)
        logic.actions.setRecipientEmail('reviewer@example.com')
        logic.actions.setRecipientDistinctId('me')
        send.mockResolvedValue(response)

        await sendTest()

        expect(toasts[kind as keyof typeof toasts]).toHaveBeenCalledWith(message)
        expect(logic.values.testSendSkipReason ?? logic.values.testSendPartialFailure).toBe(detail)
        expect(logic.values.isModalOpen).toBe(kind !== 'success')
        expect(logic.values.lastTestSentTo).toBe(vouchedFor)
    })

    it.each([
        { channel: 'email', message: 'Could not send the test email' },
        { channel: 'push', message: 'Could not send the test notification' },
    ])('reports a failed $channel request and keeps the modal open', async ({ channel, message }) => {
        if (channel === 'push') {
            await usePush()
        }
        logic.actions.setModalOpen(true)
        silenceKeaLoadersErrors()
        send.mockRejectedValue(new Error('Network down'))

        await expectLogic(logic, () => logic.actions.sendTestEmail())
            .toDispatchActions(['sendTestEmailFailure'])
            .toFinishAllListeners()

        expect(toasts.error).toHaveBeenCalledWith(message)
        expect(logic.values.isModalOpen).toBe(true)
        expect(logic.values.lastTestSentTo).toBeNull()
    })

    it('opens with the signed-in user as recipient, keeps a typed one, and drops the last result', async () => {
        userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
        wizard.actions.setEmail(READY_EMAIL)
        send.mockResolvedValue(result({ status: 'error' }))

        logic.actions.setModalOpen(true)
        expect(logic.values.recipientEmail).toBe(MOCK_DEFAULT_USER.email)
        expect(logic.values.recipientDistinctId).toBe(MOCK_DEFAULT_USER.distinct_id)

        await sendTest()
        logic.actions.setRecipientEmail('reviewer@example.com')
        logic.actions.setRecipientDistinctId('device-7')
        logic.actions.setModalOpen(false)
        logic.actions.setModalOpen(true)

        expect(logic.values.recipientEmail).toBe('reviewer@example.com')
        expect(logic.values.recipientDistinctId).toBe('device-7')
        expect(logic.values.testSendResult).toBeNull()
    })
})
