import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { Provider } from 'kea'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { resourceEditedLogic } from 'products/notifications/frontend/resourceEditedLogic'

import { MessageTemplate } from './MessageTemplate'
import { messageTemplateLogic } from './messageTemplateLogic'

interface MockCanvas {
    edit: (design: Record<string, any>) => void
    setExportGate: (gate: Promise<void> | null, onStart?: () => void) => void
}

const mockCanvases: MockCanvas[] = []

jest.mock('react-email-editor', () => {
    const React = jest.requireActual('react')
    return {
        __esModule: true,
        default: React.forwardRef(function FakeUnlayer({ onReady }: { onReady?: () => void }, ref: unknown) {
            const canvas = React.useMemo(() => {
                const listeners: Record<string, () => void> = {}
                let design: Record<string, any> = {}
                let exportGate: Promise<void> | null = null
                let onExportStart: (() => void) | undefined
                const editor = {
                    loadDesign: (next: Record<string, any>) => {
                        design = next
                        listeners['design:loaded']?.()
                    },
                    addEventListener: (event: string, callback: () => void) => {
                        listeners[event] = callback
                    },
                    exportHtml: (callback: (data: any) => void) => {
                        const deliver = (): void =>
                            callback({
                                html: design?.body?.id ? `<p>${design.body.id}</p>` : '<p>Canvas edit</p>',
                                design,
                            })
                        if (exportGate) {
                            onExportStart?.()
                            void exportGate.then(deliver)
                        } else {
                            deliver()
                        }
                    },
                    exportPlainText: (callback: (data: any) => void) =>
                        callback({ text: design?.body?.id ? String(design.body.id) : 'Canvas edit' }),
                    setMergeTags: () => {},
                    registerProvider: () => {},
                    registerCallback: () => {},
                }
                return {
                    editor,
                    edit: (next: Record<string, any>) => {
                        design = next
                        listeners['design:updated']?.()
                    },
                    setExportGate: (gate: Promise<void> | null, onStart?: () => void) => {
                        exportGate = gate
                        onExportStart = onStart
                    },
                }
            }, [])
            React.useImperativeHandle(ref, () => ({ editor: canvas.editor }), [canvas])
            React.useEffect(() => {
                mockCanvases.push(canvas)
                onReady?.()
            }, [canvas]) // oxlint-disable-line react-hooks/exhaustive-deps
            return null
        }),
    }
})

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

const IMPACT = {
    sent: 10,
    delivered: 9,
    opened: 5,
    clicked: 2,
    not_clicked: 7,
    untracked: 0,
    window_days: 7,
    after_click: null,
    without_click: null,
}

const TAGGING_OFF_TEAM = {
    ...MOCK_DEFAULT_TEAM,
    workflows_config: { capture_workflows_engagement_events: true, email_workflow_run_link_tag_enabled: false },
}

describe('MessageTemplate', () => {
    const priorAppContext = window.POSTHOG_APP_CONTEXT

    afterEach(() => {
        cleanup()
        mockCanvases.length = 0
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
        initKeaTests(true, TAGGING_OFF_TEAM)
        featureFlagLogic.mount()
        const flags = {
            [FEATURE_FLAGS.WORKFLOWS_TRANSACTIONAL_EMAIL_API]: true,
            [FEATURE_FLAGS.WORKFLOWS_EMAIL_SEND_LINKS]: true,
            ...extraFlags,
        }
        featureFlagLogic.actions.setFeatureFlags(
            Object.entries(flags)
                .filter(([, on]) => on)
                .map(([flag]) => flag),
            flags
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
        ['a sensitive template, whose links are never tagged', true, 'Not measured', false],
        ['any other template', false, 'Link tracking is off', true],
    ])('offers to turn on link tracking from the Impact tab only for %s', async (_, sensitive, label, offered) => {
        useMocks({
            get: {
                '/api/environments/:team_id/messaging_templates/:id/': { ...PASSWORD_RESET_WITH_DRAFT, sensitive },
                '/api/projects/:team_id/transactional_email_log/impact/': IMPACT,
            },
        })
        await renderAs(AccessControlLevel.Editor, PASSWORD_RESET_WITH_DRAFT.name, {
            [FEATURE_FLAGS.WORKFLOWS_EMAIL_IMPACT]: true,
        })

        fireEvent.click(screen.getByText('Impact'))

        expect(await screen.findByText(label)).toBeInTheDocument()
        expect(!!screen.queryByText('Turn on for project')).toBe(offered)
    })

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
        [AccessControlLevel.Viewer, true],
        [AccessControlLevel.Editor, false],
    ])(
        'shows the nested click tracking toggle only when sensitive is on and respects workflows %s access',
        async (workflowAccess, writeDisabled) => {
            const patchBodies: Record<string, unknown>[] = []
            const sensitiveTemplate = {
                ...PASSWORD_RESET_WITH_DRAFT,
                sensitive: true,
                click_tracking_enabled: null as boolean | null,
                updated_at: '2026-01-01T00:00:00Z',
            }
            useMocks({
                get: { '/api/environments/:team_id/messaging_templates/:id/': sensitiveTemplate },
                patch: {
                    '/api/projects/:team_id/messaging_templates/:id/': async ({ request }) => {
                        const body = (await request.json()) as Record<string, unknown>
                        patchBodies.push(body)
                        return [200, { ...sensitiveTemplate, ...body, updated_at: '2026-01-01T00:01:00Z' }]
                    },
                },
            })
            await renderAs(workflowAccess, sensitiveTemplate.name)

            fireEvent.click(screen.getByText('API'))
            const clickToggle = await screen.findByLabelText('Track link clicks')
            expect(clickToggle).toHaveAttribute('aria-checked', 'false')
            expect(clickToggle.hasAttribute('disabled')).toBe(writeDisabled)

            if (!writeDisabled) {
                fireEvent.click(clickToggle)
                await waitFor(() =>
                    expect(screen.getByLabelText('Track link clicks')).toHaveAttribute('aria-checked', 'true')
                )
                expect(patchBodies).toEqual([{ click_tracking_enabled: true }])
                expect(screen.getByText('Editing draft')).toBeInTheDocument()

                fireEvent.click(screen.getByLabelText('Track link clicks'))
                await waitFor(() =>
                    expect(screen.getByLabelText('Track link clicks')).toHaveAttribute('aria-checked', 'false')
                )
                expect(patchBodies).toEqual([{ click_tracking_enabled: true }, { click_tracking_enabled: null }])
                expect(screen.getByText('Editing draft')).toBeInTheDocument()
            }
        }
    )

    it('resets click tracking when sensitive is toggled off and back on', async () => {
        const patchBodies: Record<string, unknown>[] = []
        let serverState = {
            ...PASSWORD_RESET_WITH_DRAFT,
            sensitive: true,
            click_tracking_enabled: true as boolean | null,
            updated_at: '2026-01-01T00:00:00Z',
        }
        let tick = 1
        useMocks({
            get: { '/api/environments/:team_id/messaging_templates/:id/': () => [200, serverState] },
            patch: {
                '/api/projects/:team_id/messaging_templates/:id/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, unknown>
                    patchBodies.push(body)
                    const sensitiveChanged = 'sensitive' in body && body.sensitive !== serverState.sensitive
                    serverState = {
                        ...serverState,
                        ...body,
                        ...(sensitiveChanged ? { click_tracking_enabled: null } : {}),
                        updated_at: `2026-01-01T00:0${tick++}:00Z`,
                    }
                    return [200, serverState]
                },
            },
        })
        await renderAs(AccessControlLevel.Editor, serverState.name)

        fireEvent.click(screen.getByText('API'))
        expect(await screen.findByLabelText('Track link clicks')).toHaveAttribute('aria-checked', 'true')

        fireEvent.click(screen.getByText('Protect sensitive data'))
        await waitFor(() => expect(screen.queryByLabelText('Track link clicks')).not.toBeInTheDocument())
        expect(patchBodies).toEqual([{ sensitive: false }])

        fireEvent.click(screen.getByText('Protect sensitive data'))
        await waitFor(() => expect(screen.getByLabelText('Track link clicks')).toHaveAttribute('aria-checked', 'false'))
        expect(patchBodies).toEqual([{ sensitive: false }, { sensitive: true }])
    })

    it('hides Track link clicks and shows a notice if another tab turned sensitive off before saving', async () => {
        const serverState = {
            ...PASSWORD_RESET_WITH_DRAFT,
            sensitive: true,
            click_tracking_enabled: true as boolean | null,
            updated_at: '2026-01-01T00:00:00Z',
        }
        useMocks({
            get: { '/api/environments/:team_id/messaging_templates/:id/': () => [200, serverState] },
            patch: {
                '/api/projects/:team_id/messaging_templates/:id/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, unknown>
                    resourceEditedLogic.actions.resourceEdited({
                        notification_type: 'resource_edited',
                        team_id: 1,
                        resource_type: 'MessageTemplate',
                        resource_id: TEMPLATE_ID,
                        updated_at: '2026-01-01T00:01:00Z',
                        actor_user_id: null,
                    })
                    return [
                        200,
                        {
                            ...serverState,
                            ...body,
                            sensitive: false,
                            click_tracking_enabled: null,
                            updated_at: '2026-01-01T00:02:00Z',
                        },
                    ]
                },
            },
        })
        const infoToast = jest.spyOn(lemonToast, 'info')
        try {
            await renderAs(AccessControlLevel.Editor, serverState.name)

            fireEvent.click(screen.getByText('API'))
            const clickToggle = await screen.findByLabelText('Track link clicks')
            fireEvent.click(clickToggle)

            await waitFor(() => expect(screen.queryByLabelText('Track link clicks')).not.toBeInTheDocument())
            expect(screen.getByLabelText('Protect sensitive data')).toHaveAttribute('aria-checked', 'false')
            expect(infoToast).toHaveBeenCalledWith(
                'Sensitive data protection was turned off elsewhere, so link click tracking is on by default.'
            )
        } finally {
            infoToast.mockRestore()
            lemonToast.dismiss()
        }
    })

    it('hides the nested click tracking toggle on a non-sensitive template', async () => {
        useMocks({ get: { '/api/environments/:team_id/messaging_templates/:id/': PASSWORD_RESET_WITH_DRAFT } })
        await renderAs(AccessControlLevel.Editor, PASSWORD_RESET_WITH_DRAFT.name)

        fireEvent.click(screen.getByText('API'))
        await screen.findByLabelText('Protect sensitive data')
        expect(screen.queryByLabelText('Track link clicks')).not.toBeInTheDocument()
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
        ['a library template', urls.workflowsLibraryTemplate(TEMPLATE_ID), ORDER_RECEIPT, '', 'menu'],
        ['a transactional email', urls.transactionalTemplate(TEMPLATE_ID), PASSWORD_RESET_WITH_DRAFT, 'row', 'row'],
        [
            'a transactional email under workflows',
            urls.workflowsLibraryTemplate(TEMPLATE_ID),
            PASSWORD_RESET_WITH_DRAFT,
            '',
            'row',
        ],
        [
            'a library template without transactional emails',
            urls.workflowsLibraryTemplate(TEMPLATE_ID),
            ORDER_RECEIPT,
            'menu',
            'menu',
            { [FEATURE_FLAGS.WORKFLOWS_TRANSACTIONAL_EMAIL_API]: false },
        ],
    ])(
        'places the tags of %s while it loads and after',
        async (_, url, template, whileLoading, loadedPlace, flags: Record<string, boolean> = {}) => {
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
                ...flags,
            })
            act(() => router.actions.push(url))
            await waitFor(() => expect(tagsPlace()).toBe(whileLoading))
            // Tags edited before the saved ones arrive would replace them.
            if (whileLoading === 'row') {
                expect(screen.queryByText('Click to add tags')).not.toBeInTheDocument()
            } else if (whileLoading === 'menu') {
                fireEvent.click(screen.getByText('Metadata'))
                await waitFor(() =>
                    expect(document.querySelector('[data-attr="message-template-tags-input"]')).toBeInTheDocument()
                )
                expect(document.querySelector('[data-attr="message-template-tags-input"]')).toBeDisabled()
            }

            answer()
            await rendered
            await waitFor(() => expect(tagsPlace()).toBe(loadedPlace))
        }
    )

    it('takes a tag that did not save out of the row being edited', async () => {
        useMocks({
            get: { '/api/environments/:team_id/messaging_templates/:id/': { ...ORDER_RECEIPT, tags: ['old'] } },
            patch: { '/api/environments/:team_id/messaging_templates/:id/': () => [500, { detail: 'Boom' }] },
        })
        await renderAs(AccessControlLevel.Editor, ORDER_RECEIPT.name)
        fireEvent.click(await screen.findByText('old'))
        const input = await waitFor(() => {
            const found = document.querySelector<HTMLInputElement>(
                'input[data-attr="message-template-new-tag-input"], [data-attr="message-template-new-tag-input"] input'
            )
            expect(found).not.toBeNull()
            return found as HTMLInputElement
        })
        fireEvent.change(input, { target: { value: 'new-tag' } })
        fireEvent.keyDown(input, { key: 'Enter' })
        await waitFor(() => expect(messageTemplateLogic({ id: TEMPLATE_ID }).values.failedTagSaves).toBe(1))

        expect(screen.queryByText('new-tag')).not.toBeInTheDocument()
        expect(screen.getByText('old')).toBeInTheDocument()
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

    it('disables Publish while discarding a draft and sends no publish request until discard finishes', async () => {
        let releaseDiscard!: () => void
        const discardGate = new Promise<void>((resolve) => {
            releaseDiscard = resolve
        })
        let discardStarted!: () => void
        const discardArrived = new Promise<void>((resolve) => {
            discardStarted = resolve
        })
        const patchBodies: Record<string, unknown>[] = []
        const patch = async ({ request }: { request: Request }): Promise<[number, Record<string, unknown>]> => {
            const body = (await request.json()) as Record<string, unknown>
            patchBodies.push(body)
            if ('draft_content' in body && body.draft_content === null) {
                discardStarted()
                await discardGate
                return [
                    200,
                    {
                        ...PASSWORD_RESET_WITH_DRAFT,
                        draft_content: null,
                        updated_at: '2026-01-01T00:01:00Z',
                    },
                ]
            }
            return [200, { ...PASSWORD_RESET_WITH_DRAFT, ...body, draft_content: null }]
        }
        useMocks({
            get: { '/api/environments/:team_id/messaging_templates/:id/': PASSWORD_RESET_WITH_DRAFT },
            patch: {
                '/api/environments/:team_id/messaging_templates/:id/': patch,
                '/api/projects/:team_id/messaging_templates/:id/': patch,
            },
        })
        await renderAs(AccessControlLevel.Editor, PASSWORD_RESET_WITH_DRAFT.name)

        fireEvent.click(screen.getByLabelText('More draft actions'))
        const discardMenuItem = await waitFor(() => {
            const item = document.querySelector<HTMLElement>('[data-attr="message-template-discard-draft"]')
            expect(item).not.toBeNull()
            return item as HTMLElement
        })
        fireEvent.click(discardMenuItem)
        const dialog = await screen.findByRole('dialog')
        fireEvent.click(within(dialog).getByText('Discard draft'))
        await discardArrived

        const publishButton = screen.getByText('Publish').closest('button') as HTMLButtonElement
        expect(publishButton).toHaveAttribute('aria-disabled', 'true')
        fireEvent.click(publishButton)
        expect(patchBodies).toEqual([{ draft_content: null }])

        await act(async () => releaseDiscard())
        await waitFor(() => expect(screen.queryByText('Editing draft')).not.toBeInTheDocument())
        expect(patchBodies).toEqual([{ draft_content: null }])
    })

    it('keeps Publish disabled while reconciling an older publish response with a pending canvas export', async () => {
        let releasePublish!: () => void
        const publishGate = new Promise<void>((resolve) => {
            releasePublish = resolve
        })
        let publishStarted!: () => void
        const publishArrived = new Promise<void>((resolve) => {
            publishStarted = resolve
        })
        let releaseExport!: () => void
        const exportGate = new Promise<void>((resolve) => {
            releaseExport = resolve
        })
        let exportStarted!: () => void
        const exportArrived = new Promise<void>((resolve) => {
            exportStarted = resolve
        })
        let currentServer: Record<string, unknown> = {
            ...PASSWORD_RESET_WITH_DRAFT,
            sensitive: true,
            click_tracking_enabled: null,
            updated_at: '2026-01-01T00:00:00Z',
        }
        const newerServerDraft = {
            templating: 'liquid',
            email: { subject: 'From another tab', html: '<p>Other tab draft</p>', text: 'Other tab draft' },
        }
        const publishBodies: Record<string, unknown>[] = []
        const patch = async ({ request }: { request: Request }): Promise<[number, Record<string, unknown>]> => {
            const body = (await request.json()) as Record<string, unknown>
            if ('click_tracking_enabled' in body) {
                await publishArrived
                currentServer = {
                    ...currentServer,
                    ...body,
                    draft_content: newerServerDraft,
                    updated_at: '2026-01-01T00:02:00Z',
                }
                return [200, { ...currentServer }]
            }
            publishBodies.push(body)
            currentServer = {
                ...currentServer,
                ...body,
                draft_content: null,
                updated_at: '2026-01-01T00:01:00Z',
            }
            const publishResponse = { ...currentServer }
            publishStarted()
            await publishGate
            return [200, publishResponse]
        }
        useMocks({
            get: { '/api/environments/:team_id/messaging_templates/:id/': () => [200, { ...currentServer }] },
            patch: {
                '/api/environments/:team_id/messaging_templates/:id/': patch,
                '/api/projects/:team_id/messaging_templates/:id/': patch,
            },
        })
        await renderAs(AccessControlLevel.Editor, PASSWORD_RESET_WITH_DRAFT.name)

        const canvas = mockCanvases.at(-1)
        expect(canvas).not.toBeUndefined()

        fireEvent.click(screen.getByText('API'))
        const clickTrackingSwitch = await screen.findByLabelText('Track link clicks')
        fireEvent.click(clickTrackingSwitch)
        fireEvent.click(screen.getByText('Publish'))
        await publishArrived
        await waitFor(() => expect(screen.getByLabelText('Track link clicks')).toHaveAttribute('aria-checked', 'true'))

        fireEvent.click(screen.getByText('Design'))
        fireEvent.click(screen.getByText(PASSWORD_RESET_WITH_DRAFT.name))
        const nameInput = await screen.findByPlaceholderText('Enter name')
        fireEvent.change(nameInput, { target: { value: 'Edited during publish' } })
        fireEvent.blur(nameInput)
        expect(screen.queryByPlaceholderText('Enter name')).not.toBeInTheDocument()

        canvas!.setExportGate(exportGate, exportStarted)
        act(() => {
            canvas!.edit({ body: { id: 'Canvas edit' } })
            releasePublish()
        })
        await exportArrived

        const publishButton = screen.getByText('Publish').closest('button') as HTMLButtonElement
        await waitFor(() => expect(publishButton).toHaveAttribute('aria-disabled', 'true'))
        fireEvent.click(publishButton)
        expect(publishBodies).toHaveLength(1)
        expect(currentServer.draft_content).toEqual(newerServerDraft)

        await act(async () => releaseExport())
        expect(await screen.findByText(/This template was updated elsewhere/)).toBeInTheDocument()
        expect(screen.getByText('Edited during publish')).toBeInTheDocument()
        expect(publishBodies).toHaveLength(1)
        expect(currentServer.draft_content).toEqual(newerServerDraft)
    })
})
