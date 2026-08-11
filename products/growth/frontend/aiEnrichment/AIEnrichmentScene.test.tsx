import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { LemonDialog } from '@posthog/lemon-ui'

import type { ConfigVersionApi } from '../generated/api.schemas'
import { AIEnrichmentVersionRail } from './AIEnrichmentScene'

jest.mock('kea', () => ({ ...jest.requireActual('kea'), useActions: jest.fn(), useValues: jest.fn() }))
jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    LemonDialog: { open: jest.fn(), openForm: jest.fn() },
}))

const ACTIVE_VERSION: ConfigVersionApi = {
    id: 'config-v1',
    name: 'test_label',
    version: 'v1',
    prompt_text: '',
    model: 'gpt-5-mini',
    input_fields: [],
    output_fields: [],
    is_active: true,
    created_by_email: null,
    created_at: '2024-01-01T00:00:00Z',
    has_results: false,
}
const DRAFT_VERSION: ConfigVersionApi = { ...ACTIVE_VERSION, id: 'config-v2', version: 'v2', is_active: false }

describe('AIEnrichmentVersionRail', () => {
    const activateVersion = jest.fn()
    const loadVersionIntoEditor = jest.fn()
    const open = LemonDialog.open as jest.Mock

    afterEach(cleanup)

    beforeEach(() => {
        ;[activateVersion, loadVersionIntoEditor, open].forEach((mockFn) => mockFn.mockClear())
        ;(useActions as jest.Mock).mockReturnValue({ activateVersion, loadVersionIntoEditor })
    })

    function renderRail(isEditorDirty: boolean): void {
        ;(useValues as jest.Mock).mockReturnValue({
            selectedLabel: 'test_label',
            versions: [ACTIVE_VERSION, DRAFT_VERSION],
            configsLoading: false,
            activeVersion: ACTIVE_VERSION,
            selectedVersionId: DRAFT_VERSION.id,
            activateResultLoading: false,
            isEditorDirty,
        })
        render(<AIEnrichmentVersionRail />)
    }

    it('shows the real active version in the header, not whichever version is being viewed', () => {
        renderRail(false)
        // selectedVersionId points at the draft (v2); the header must still read the active one.
        expect(document.querySelector('[data-attr="ai-enrichment-active-version"]')).toHaveTextContent('v1')
    })

    it('activates immediately, with no discard warning, when there are no unsaved edits', () => {
        renderRail(false)

        fireEvent.click(screen.getByText('Activate'))

        expect(open).toHaveBeenCalledTimes(1)
        const dialogConfig = open.mock.calls[0][0]
        expect(dialogConfig.description).not.toMatch(/discard|unsaved/i)
        expect(activateVersion).not.toHaveBeenCalled()
        // Clicking Activate must only ever open the confirm dialog, never select the row
        // underneath it - a broken closest('button') guard on the row's onClick would fire this
        // too and pass silently if this assertion weren't here.
        expect(loadVersionIntoEditor).not.toHaveBeenCalled()

        dialogConfig.primaryButton.onClick()
        expect(activateVersion).toHaveBeenCalledWith(DRAFT_VERSION.id)
    })

    it('warns that unsaved edits will be discarded before activating a different version', () => {
        renderRail(true)

        fireEvent.click(screen.getByText('Activate'))

        expect(open).toHaveBeenCalledTimes(1)
        const dialogConfig = open.mock.calls[0][0]
        expect(dialogConfig.description).toMatch(/discard/i)
        // The gate gives the user one more chance to back out - activating must not happen until
        // they click through the warning, not on the first click of the Activate button itself.
        expect(activateVersion).not.toHaveBeenCalled()

        dialogConfig.primaryButton.onClick()
        expect(activateVersion).toHaveBeenCalledWith(DRAFT_VERSION.id)
    })
})
