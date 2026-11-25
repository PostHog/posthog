import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { Provider } from 'kea'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { MessageTemplate } from './MessageTemplate'
import { messageTemplateLogic } from './messageTemplateLogic'

const TEMPLATE_ID = 'tmpl-1'

const ORDER_RECEIPT = {
    id: TEMPLATE_ID,
    name: 'Order receipt',
    description: '',
    tags: [],
    content: { email: { subject: 'Hi', html: '<p>Hi</p>', text: 'Hi', design: {} } },
}

const PASSWORD_RESET_WITH_DRAFT = {
    ...ORDER_RECEIPT,
    name: 'Password reset',
    transactional_hog_flow_id: 'flow-1',
    sensitive: false,
    draft_content: { email: { subject: 'Reset it', html: '<p>Reset</p>', text: 'Reset', design: {} } },
}

describe('MessageTemplate', () => {
    const priorAppContext = window.POSTHOG_APP_CONTEXT

    afterEach(() => {
        cleanup()
        window.POSTHOG_APP_CONTEXT = priorAppContext
    })

    const renderAs = async (
        workflowAccess: AccessControlLevel,
        templateName: string,
        extraFlags: Record<string, boolean> = {}
    ): Promise<void> => {
        window.POSTHOG_APP_CONTEXT = {
            ...priorAppContext,
            resource_access_control: {
                ...priorAppContext?.resource_access_control,
                [AccessControlResourceType.Workflow]: workflowAccess,
            },
        } as AppContext
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags(
            [FEATURE_FLAGS.WORKFLOWS_TRANSACTIONAL_EMAIL_API, FEATURE_FLAGS.WORKFLOWS_EMAIL_SEND_LINKS],
            {
                [FEATURE_FLAGS.WORKFLOWS_TRANSACTIONAL_EMAIL_API]: true,
                [FEATURE_FLAGS.WORKFLOWS_EMAIL_SEND_LINKS]: true,
                ...extraFlags,
            }
        )

        render(
            <Provider>
                <MessageTemplate id={TEMPLATE_ID} />
            </Provider>
        )

        await waitFor(() => expect(screen.getByText(templateName)).toBeInTheDocument())
    }

    it.each([
        [AccessControlLevel.Viewer, false, 'true'],
        [AccessControlLevel.Editor, true, 'false'],
    ])(
        'lets a workflows %s rename the template=%s and gives it disabled write actions=%s',
        async (workflowAccess, canRename, expectedWriteDisabled) => {
            useMocks({ get: { '/api/environments/:team_id/messaging_templates/:id/': ORDER_RECEIPT } })
            await renderAs(workflowAccess, ORDER_RECEIPT.name)

            fireEvent.click(screen.getByText('Order receipt'))
            expect(!!screen.queryByPlaceholderText('Enter name')).toBe(canRename)

            expect(document.querySelector('[data-attr="send-test-message-template"]')).toHaveAttribute(
                'aria-disabled',
                expectedWriteDisabled
            )

            fireEvent.click(screen.getByLabelText('more'))
            await waitFor(() =>
                expect(document.querySelector('[data-attr="delete-message-template"]')).toBeInTheDocument()
            )
            expect(document.querySelector('[data-attr="delete-message-template"]')).toHaveAttribute(
                'aria-disabled',
                expectedWriteDisabled
            )

            fireEvent.click(screen.getByText('API'))
            await waitFor(() =>
                expect(document.querySelector('[data-attr="make-message-template-transactional"]')).toBeInTheDocument()
            )
            expect(document.querySelector('[data-attr="make-message-template-transactional"]')).toHaveAttribute(
                'aria-disabled',
                expectedWriteDisabled
            )
        }
    )

    it.each([
        [AccessControlLevel.Viewer, true],
        [AccessControlLevel.Editor, false],
    ])(
        'blocks a workflows %s from publishing, discarding or marking a transactional draft sensitive: %s',
        async (workflowAccess, writeDisabled) => {
            useMocks({ get: { '/api/environments/:team_id/messaging_templates/:id/': PASSWORD_RESET_WITH_DRAFT } })
            await renderAs(workflowAccess, PASSWORD_RESET_WITH_DRAFT.name)

            expect(screen.getByText('Publish').closest('button')).toHaveAttribute(
                'aria-disabled',
                String(writeDisabled)
            )

            fireEvent.click(screen.getByLabelText('More draft actions'))
            await waitFor(() =>
                expect(document.querySelector('[data-attr="message-template-discard-draft"]')).toBeInTheDocument()
            )
            expect(document.querySelector('[data-attr="message-template-discard-draft"]')).toHaveAttribute(
                'aria-disabled',
                String(writeDisabled)
            )

            fireEvent.click(screen.getByText('API'))
            await waitFor(() => expect(screen.getByLabelText('Protect sensitive data')).toBeInTheDocument())
            expect(screen.getByLabelText('Protect sensitive data').hasAttribute('disabled')).toBe(writeDisabled)
        }
    )

    it.each([
        ['the transactional library', urls.transactionalTemplate(TEMPLATE_ID)],
        ['the workflows library', urls.workflowsLibraryTemplate(TEMPLATE_ID)],
    ])("opens the sends behind a clicked email metric on the template's own Sends tab, from %s", async (_, url) => {
        const sendRequests: Record<string, string>[] = []
        useMocks({
            get: {
                '/api/environments/:team_id/messaging_templates/:id/': PASSWORD_RESET_WITH_DRAFT,
                '/api/projects/:team_id/transactional_email_log/': ({ request }) => {
                    sendRequests.push(Object.fromEntries(new URL(request.url).searchParams))
                    return [200, { results: [], has_more: false }]
                },
                '/api/environments/:team_id/hog_flows/:id/': {
                    id: 'flow-1',
                    actions: [{ id: 'email-step', name: 'Password reset email', type: 'function_email', config: {} }],
                },
            },
            post: {
                '/api/environments/:team_id/query/:query_kind/': async ({ request }) => {
                    const { query } = ((await request.json()) as { query: { query: string } }).query
                    const isEmailTotals =
                        query.includes('instance_id, metric_name') && query.includes('email_bounced_hard')
                    return [
                        200,
                        {
                            results: isEmailTotals
                                ? [
                                      [10, 'email-step', 'email_sent'],
                                      [2, 'email-step', 'email_bounced_hard'],
                                  ]
                                : [],
                        },
                    ]
                },
            },
        })
        await renderAs(AccessControlLevel.Editor, PASSWORD_RESET_WITH_DRAFT.name)

        router.actions.push(url)
        const page = router.values.location.pathname
        fireEvent.click(screen.getByText('Metrics'))
        fireEvent.click(await screen.findByText(/^2 hard bounced/))

        await screen.findByText('No sends match these filters')
        expect(router.values.location.pathname).toEqual(page)
        expect(sendRequests.at(-1)).toMatchObject({ workflow_id: 'flow-1', status: 'bounced', reason: 'hard' })
    })

    it('opens the run logs from a template link saved before the Sends list, until the reader picks Sends', async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/messaging_templates/:id/': PASSWORD_RESET_WITH_DRAFT,
                '/api/environments/:team_id/hog_flows/:id/': { id: 'flow-1', actions: [] },
                '/api/projects/:team_id/transactional_email_log/': {
                    results: [
                        {
                            message_id: 'msg-1',
                            recipient: 'ada@example.com',
                            status: 'failed',
                            created_at: '2026-03-14T10:00:00Z',
                        },
                    ],
                    has_more: false,
                },
            },
            post: { '/api/environments/:team_id/query/': { results: [] } },
        })
        await renderAs(AccessControlLevel.Editor, PASSWORD_RESET_WITH_DRAFT.name)

        router.actions.push(urls.transactionalTemplate(TEMPLATE_ID), { tab: 'sends', inv_search: 'Transient bounce' })

        expect(await screen.findByText('Re-run…')).toBeInTheDocument()
        expect(screen.queryByText('ada@example.com')).not.toBeInTheDocument()

        fireEvent.click(screen.getByText('Sends'))

        expect(await screen.findByText('ada@example.com')).toBeInTheDocument()
        expect(router.values.searchParams).toEqual({ tab: 'sends' })
    })

    it.each([
        ['a library template', ORDER_RECEIPT, {}, 'row'],
        ['a library template with the menu bar', ORDER_RECEIPT, { [FEATURE_FLAGS.SCENE_MENU_BAR]: true }, 'menu'],
        ['a library template with the rail', ORDER_RECEIPT, { [FEATURE_FLAGS.TODAY_RAIL_NAV]: true }, 'menu'],
        [
            'a transactional template with the menu bar',
            PASSWORD_RESET_WITH_DRAFT,
            { [FEATURE_FLAGS.SCENE_MENU_BAR]: true },
            'row',
        ],
    ])('keeps tags reachable in one place: %s', async (_, template, flags, place) => {
        useMocks({ get: { '/api/environments/:team_id/messaging_templates/:id/': template } })
        await renderAs(AccessControlLevel.Editor, template.name, flags)

        await waitFor(() =>
            expect([
                !!document.querySelector('[data-attr="message-template-tags-button"]'),
                !!document.querySelector('[data-attr="message-template-menubar-metadata"]'),
            ]).toEqual([place === 'row', place === 'menu'])
        )
    })

    it.each([
        ['a library template', ORDER_RECEIPT, true],
        ['a transactional template', PASSWORD_RESET_WITH_DRAFT, false],
    ])('description toggle of %s', async (_, template, hasToggle) => {
        useMocks({ get: { '/api/environments/:team_id/messaging_templates/:id/': template } })
        await renderAs(AccessControlLevel.Editor, template.name)
        expect(await screen.findByText('Enter description (optional)')).toBeInTheDocument()
        await waitFor(() =>
            expect(!!document.querySelector('[data-attr="toggle-description-button-collapse"]')).toBe(hasToggle)
        )
    })

    it('puts subject, preheader and the content switch of a library template on one row', async () => {
        useMocks({ get: { '/api/environments/:team_id/messaging_templates/:id/': ORDER_RECEIPT } })
        await renderAs(AccessControlLevel.Editor, ORDER_RECEIPT.name, {
            [FEATURE_FLAGS.WORKFLOWS_EMAIL_DOCUMENT_EDITOR]: true,
        })

        const row = (await screen.findByText('Subject')).closest('.border-b') as HTMLElement
        expect(within(row).getByLabelText('Preheader')).toBeInTheDocument()
        expect(within(row).getByText('Plain text')).toBeInTheDocument()
        expect(screen.getAllByText('Plain text')).toHaveLength(1)
    })

    it.each([
        ['a library template', urls.workflowsLibraryTemplate(TEMPLATE_ID), ORDER_RECEIPT, 'menu', 'menu'],
        ['a transactional email', urls.transactionalTemplate(TEMPLATE_ID), PASSWORD_RESET_WITH_DRAFT, 'row', 'row'],
        [
            'a transactional email under workflows',
            urls.workflowsLibraryTemplate(TEMPLATE_ID),
            PASSWORD_RESET_WITH_DRAFT,
            'menu',
            'row',
        ],
    ])('places the tags of %s while it loads and after', async (_, url, template, whileLoading, loadedPlace) => {
        let answer: () => void = () => {}
        const loaded = new Promise<void>((resolve) => (answer = resolve))
        useMocks({
            get: {
                '/api/environments/:team_id/messaging_templates/:id/': async () => {
                    await loaded
                    return [200, template]
                },
            },
        })
        const tagsPlace = (): string =>
            [
                document.querySelector('[data-attr="message-template-tags-button"]') && 'row',
                document.querySelector('[data-attr="message-template-menubar-metadata"]') && 'menu',
            ]
                .filter(Boolean)
                .join()
        const rendered = renderAs(AccessControlLevel.Editor, template.name, {
            [FEATURE_FLAGS.SCENE_MENU_BAR]: true,
        })
        act(() => router.actions.push(url))
        await waitFor(() => expect(tagsPlace()).toBe(whileLoading))
        // Tags edited before the saved ones arrive would replace them.
        if (whileLoading === 'row') {
            expect(screen.queryByText('Click to add tags')).not.toBeInTheDocument()
        } else {
            fireEvent.click(screen.getByText('Metadata'))
            await waitFor(() =>
                expect(document.querySelector('[data-attr="message-template-tags-input"]')).toBeInTheDocument()
            )
            expect(document.querySelector('[data-attr="message-template-tags-input"]')).toBeDisabled()
        }

        answer()
        await rendered
        await waitFor(() => expect(tagsPlace()).toBe(loadedPlace))
    })

    it('keeps the open editor while it saves', async () => {
        let releaseSave = (): void => {}
        useMocks({
            get: { '/api/environments/:team_id/messaging_templates/:id/': ORDER_RECEIPT },
            patch: {
                '/api/environments/:team_id/messaging_templates/:id/': async () => {
                    await new Promise<void>((resolve) => (releaseSave = resolve))
                    return [200, { ...ORDER_RECEIPT, name: 'Renamed' }]
                },
            },
        })
        await renderAs(AccessControlLevel.Editor, ORDER_RECEIPT.name)
        const logic = messageTemplateLogic({ id: TEMPLATE_ID })
        const subject = await screen.findByText('Subject')
        act(() => logic.actions.setTemplateValue('name', 'Renamed'))

        fireEvent.click(screen.getByText('Save'))
        await waitFor(() => expect(logic.values.savedTemplateLoading).toBe(true))
        expect(subject).toBeInTheDocument()

        await act(async () => releaseSave())
        await waitFor(() => expect(logic.values.templateChanged).toBe(false))
        expect(subject).toBeInTheDocument()
    })
})
