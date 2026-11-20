import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toBlob } from 'html-to-image'
import { ToastContainer } from 'react-toastify'

import { downloadFile } from 'lib/utils/dom'

import { initKeaTests } from '~/test/init'

import { notebookExportLogic } from './notebookExportLogic'
import { NotebookImageExportControls } from './NotebookImageExportControls'

jest.mock('html-to-image', () => ({ toBlob: jest.fn() }))
jest.mock('lib/utils/dom', () => ({
    ...jest.requireActual('lib/utils/dom'),
    downloadFile: jest.fn(),
}))

describe('NotebookImageExportControls', () => {
    let logic: ReturnType<typeof notebookExportLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        logic = notebookExportLogic({ shortId: 'export-test' })
        logic.mount()
        logic.actions.prepareImage()
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    it('keeps preparation open and explains how to export an embedded widget instead of downloading a blank frame', async () => {
        render(
            <>
                <div className="Notebook" data-notebook-short-id="export-test">
                    <iframe title="Generated widget" sandbox="allow-scripts" />
                    <NotebookImageExportControls
                        shortId="export-test"
                        title="Weekly report"
                        onCancel={logic.actions.cancelPrint}
                    />
                </div>
                <ToastContainer />
            </>
        )

        await userEvent.click(screen.getByText('Download PNG'))

        expect(
            await screen.findByText('PNG export cannot include embedded frames. Use Print / save PDF instead.')
        ).toBeInTheDocument()
        expect(downloadFile).not.toHaveBeenCalled()
        expect(logic.values.preparingPrint).toBe(true)
        expect(screen.getByText('Cancel')).toBeEnabled()
    })

    it.each([false, true])(
        'clears preparation only after a successful download, captureFails=%s',
        async (captureFails) => {
            if (captureFails) {
                jest.mocked(toBlob).mockRejectedValueOnce(new Error('Capture failed'))
            } else {
                jest.mocked(toBlob).mockResolvedValueOnce(new Blob(['png'], { type: 'image/png' }))
            }
            render(
                <>
                    <div className="Notebook" data-notebook-short-id="export-test">
                        Notebook results
                        <NotebookImageExportControls
                            shortId="export-test"
                            title="Weekly report"
                            onCancel={logic.actions.cancelPrint}
                        />
                    </div>
                    <ToastContainer />
                </>
            )

            await userEvent.click(screen.getByText('Download PNG'))
            await userEvent.click(await screen.findByText('Export PNG', { selector: '.LemonButton__content' }))

            expect(
                await screen.findByText(captureFails ? 'Could not create the image. Try again.' : 'Image downloaded')
            ).toBeInTheDocument()
            await waitFor(() => expect(logic.values.preparingPrint).toBe(captureFails))
            expect(screen.getByText('Download PNG')).toBeEnabled()
            if (captureFails) {
                expect(downloadFile).not.toHaveBeenCalled()
            } else {
                expect(jest.mocked(downloadFile).mock.calls[0][0].name).toBe('weekly-report.png')
            }
        }
    )
})
