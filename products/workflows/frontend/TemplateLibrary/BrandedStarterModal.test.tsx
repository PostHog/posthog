import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { router } from 'kea-router'

import { emailTemplaterLogic } from 'scenes/hog-functions/email-templater/emailTemplaterLogic'
import type { EditorRef } from 'scenes/hog-functions/email-templater/emailTemplaterLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { BrandedStarterModal } from './BrandedStarterModal'
import { NEW_TEMPLATE } from './constants'
import { messageTemplateSceneLogic } from './messageTemplateSceneLogic'

describe('branded starter modal', () => {
    beforeEach(() => {
        useMocks({})
        initKeaTests()
    })

    afterEach(cleanup)

    it('offers a focusable logo picker', () => {
        render(<BrandedStarterModal id="new" />)
        const choose = document.querySelector<HTMLElement>('[data-attr="email-branded-starter-logo-choose"]')!
        choose.focus()
        expect(choose).toHaveFocus()

        const onOpen = jest.fn()
        screen.getByRole('dialog').querySelector('input[type="file"]')!.addEventListener('click', onOpen)
        fireEvent.click(choose)
        expect(onOpen).toHaveBeenCalledTimes(1)
    })

    it('lets a user remove a selected logo without losing their other inputs', () => {
        render(<BrandedStarterModal id="new" />)
        fireEvent.change(screen.getByLabelText('Brand name'), { target: { value: 'Juniper Studio' } })
        const color = screen.getByLabelText('Primary color')
        fireEvent.change(color, { target: { value: '#ffd400' } })
        fireEvent.change(screen.getByRole('dialog').querySelector<HTMLInputElement>('input[type="file"]')!, {
            target: { files: [new File(['logo'], 'logo.png', { type: 'image/png' })] },
        })
        expect(screen.getByText('logo.png')).toBeInTheDocument()

        const remove = document.querySelector<HTMLElement>('[data-attr="email-branded-starter-logo-remove"]')!
        remove.focus()
        fireEvent.click(remove)

        expect(screen.queryByText('logo.png')).not.toBeInTheDocument()
        expect(document.querySelector<HTMLElement>('[data-attr="email-branded-starter-logo-choose"]')!).toHaveFocus()
        expect(screen.getByLabelText('Brand name')).toHaveValue('Juniper Studio')
        expect(color).toHaveValue('#ffd400')
    })

    it('keeps the entered brand when the overlay is clicked', () => {
        router.actions.push('/workflows/library/templates/new')
        render(<BrandedStarterModal id="new" />)
        fireEvent.change(screen.getByLabelText('Brand name'), { target: { value: 'Juniper Studio' } })

        fireEvent.click(document.querySelector('.LemonModal__overlay')!)

        expect(router.values.location.pathname).toContain('/workflows/library/templates/new')
        expect(screen.getByLabelText('Brand name')).toHaveValue('Juniper Studio')
    })

    it('keeps Esc working from the keyboard while a slow logo upload runs', async () => {
        useMocks({ post: { '/api/projects/:team_id/uploaded_media/': () => new Promise(() => {}) } })
        const templater = emailTemplaterLogic({
            value: NEW_TEMPLATE.content.email,
            onChange: jest.fn(),
            type: 'native_email_template',
            layout: 'inline',
        })
        templater.mount()
        const editor = { addEventListener: jest.fn(), loadDesign: jest.fn(), exportHtml: jest.fn() }
        templater.actions.setEmailEditorRef({ editor } as unknown as EditorRef)
        templater.actions.onEmailEditorReady()
        router.actions.push('/workflows/library/templates/new')
        render(<BrandedStarterModal id="new" />)
        fireEvent.change(screen.getByLabelText('Brand name'), { target: { value: 'Juniper Studio' } })
        fireEvent.change(screen.getByRole('dialog').querySelector<HTMLInputElement>('input[type="file"]')!, {
            target: { files: [new File(['logo'], 'logo.png', { type: 'image/png' })] },
        })

        screen.getByLabelText('Brand name').focus()
        fireEvent.submit(document.getElementById('branded-starter')!)
        await waitFor(() => expect(screen.getByLabelText('Brand name')).toBeDisabled())
        const generate = document.querySelector<HTMLElement>('[data-attr="email-branded-starter-generate"]')!
        expect(generate).toHaveFocus()
        fireEvent.keyDown(generate, { key: 'Escape', keyCode: 27 })

        expect(router.values.location.pathname).not.toContain('/templates/new')
        templater.unmount()
    })

    it('keeps the entered brand when the scene tab is hidden and shown again', () => {
        const scene = messageTemplateSceneLogic({ id: 'new' })
        scene.mount()
        const firstVisit = render(<BrandedStarterModal id="new" />)
        fireEvent.change(screen.getByLabelText('Brand name'), { target: { value: 'Juniper Studio' } })

        firstVisit.unmount()
        render(<BrandedStarterModal id="new" />)

        expect(screen.getByLabelText('Brand name')).toHaveValue('Juniper Studio')
        scene.unmount()
    })
    describe('detecting from a GitHub repository', () => {
        const githubIntegration = {
            id: 7,
            kind: 'github',
            display_name: 'juniper',
            icon_url: '',
            config: { account: { type: 'Organization', name: 'juniper' } },
            created_at: '2026-01-01T00:00:00Z',
            errors: '',
        }

        it('reads the brand from the likeliest repository and fills the form', async () => {
            const detectRequests: unknown[] = []
            useMocks({
                get: {
                    '/api/projects/:team_id/integrations/': () => [200, { results: [githubIntegration], next: null }],
                    '/api/projects/:team_id/integrations/:id/github_repos/': () => [
                        200,
                        {
                            repositories: [
                                {
                                    id: 1,
                                    name: 'old-site',
                                    full_name: 'juniper/old-site',
                                    pushed_at: '2020-01-01T00:00:00Z',
                                },
                                {
                                    id: 2,
                                    name: 'juniper-web',
                                    full_name: 'Juniper/juniper-web',
                                    pushed_at: '2026-05-01T00:00:00Z',
                                },
                            ],
                            has_more: false,
                        },
                    ],
                },
                post: {
                    '/api/projects/:team_id/email_brand/detect_from_github/': async ({ request }) => {
                        detectRequests.push(await request.json())
                        return [
                            200,
                            {
                                repository: 'juniper/juniper-web',
                                name: 'Juniper Cloud',
                                primary_color: '#2e7d32',
                                logo_url: null,
                            },
                        ]
                    },
                },
            })
            render(<BrandedStarterModal id="new" />)

            fireEvent.click(document.querySelector<HTMLElement>('[data-attr="email-branded-starter-github-open"]')!)
            await waitFor(() =>
                expect(
                    document.querySelector<HTMLElement>('[data-attr="email-branded-starter-github-detect"]')!
                ).not.toHaveAttribute('aria-disabled', 'true')
            )
            fireEvent.click(document.querySelector<HTMLElement>('[data-attr="email-branded-starter-github-detect"]')!)

            await waitFor(() => expect(screen.getByLabelText('Brand name')).toHaveValue('Juniper Cloud'))
            expect(screen.getByLabelText('Primary color')).toHaveValue('#2e7d32')
            expect(detectRequests).toEqual([{ integration_id: 7, repository: 'Juniper/juniper-web' }])
            expect(screen.getByText(/We filled this in from juniper\/juniper-web/)).toHaveTextContent('on GitHub')
        })

        it.each([
            [
                'shares no repositories',
                [200, { repositories: [], has_more: false }],
                /cannot see any repositories/,
                'Check again',
            ],
            [
                'fails to list its repositories',
                [500, { detail: 'Server error' }],
                /Could not load your GitHub repositories/,
                'Try again',
            ],
        ])('explains an installation that %s', async (_case, answer, message, retry) => {
            useMocks({
                get: {
                    '/api/projects/:team_id/integrations/': () => [200, { results: [githubIntegration], next: null }],
                    '/api/projects/:team_id/integrations/:id/github_repos/': () => answer,
                },
            })
            render(<BrandedStarterModal id="new" />)

            fireEvent.click(document.querySelector<HTMLElement>('[data-attr="email-branded-starter-github-open"]')!)

            expect(await screen.findByText(message)).toBeInTheDocument()
            expect(screen.getAllByText(retry).length).toBeGreaterThan(0)
        })

        it('offers to connect GitHub and come back to the starter', async () => {
            useMocks({ get: { '/api/projects/:team_id/integrations/': () => [200, { results: [], next: null }] } })
            router.actions.push('/workflows/library/templates/new', { brandedStarter: 'true' })
            render(<BrandedStarterModal id="new" />)

            fireEvent.click(document.querySelector<HTMLElement>('[data-attr="email-branded-starter-github-open"]')!)

            const connect = (await screen.findByText('Connect GitHub')).closest('a')!
            const authorizeUrl = new URL(connect.getAttribute('href')!, 'http://localhost')
            expect(authorizeUrl.searchParams.get('kind')).toBe('github')
            expect(authorizeUrl.searchParams.get('next')).toContain(
                '/workflows/library/templates/new?brandedStarter=true'
            )
        })
    })
})
