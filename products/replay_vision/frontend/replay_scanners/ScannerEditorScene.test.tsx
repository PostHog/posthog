import '@testing-library/jest-dom'

import { cleanup, render, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { VisionQuotaApi } from '../generated/api.schemas'
import { visionQuotaLogic } from '../logics/visionQuotaLogic'
import { makeQuota } from '../utils/quotaTestUtils'
import { EditorFooter } from './ScannerEditorScene'

function renderFooter(): ReturnType<typeof render> {
    return render(
        <Provider>
            <EditorFooter
                step="self_driving"
                scannerId="new"
                visibleSteps={['configure', 'triggers', 'self_driving']}
                isNew
                isSubmitting={false}
                onAdvance={() => {}}
                onSave={() => {}}
            />
        </Provider>
    )
}

describe('ScannerEditorScene EditorFooter', () => {
    let quota: VisionQuotaApi

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/vision/quota/': () => [200, quota],
                '/api/billing/': () => [200, {}],
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    // The create button used to stay a live CTA next to the "free credits used up" note, so a new scanner
    // got made on an exhausted budget and read as "in progress" forever. Gate it, and show the billing link
    // beside it (the final step has no other quota signal, unlike the triggers step's cost forecast).
    it('gates the create button and offers billing when quota is exhausted', async () => {
        quota = makeQuota({ credits_used: 10_000, remaining: 0, exhausted: true })
        const { getByText, getByTestId } = renderFooter()
        await waitFor(() => expect(visionQuotaLogic.findMounted()?.values.quota?.exhausted).toBe(true))

        expect(getByTestId('vision-editor-save')).toHaveAttribute('aria-disabled', 'true')
        expect(getByText(/billing/i)).toBeInTheDocument()
    })

    it('shows no billing note when credits remain', async () => {
        quota = makeQuota()
        const { queryByText } = renderFooter()
        await waitFor(() => expect(visionQuotaLogic.findMounted()?.values.quota?.exhausted).toBe(false))

        expect(queryByText(/billing/i)).not.toBeInTheDocument()
    })
})
