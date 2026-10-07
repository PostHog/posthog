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
})
