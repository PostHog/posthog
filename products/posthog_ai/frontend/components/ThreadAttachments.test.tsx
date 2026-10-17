import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { projectLogic } from 'scenes/projectLogic'

import { initKeaTests } from '~/test/init'

import { clearAttachmentPreviews, rememberAttachmentPreview } from '../utils/attachmentPreviews'
import { ThreadAttachments } from './ThreadAttachments'

const RESOLVED = { taskId: 'task-3', runId: 'run-7', artifactId: 'art-9' }
const DOWNLOAD_URL = '/api/projects/997/tasks/task-3/runs/run-7/artifacts/art-9/download/'

describe('ThreadAttachments', () => {
    beforeEach(() => {
        initKeaTests()
        projectLogic.mount()
        clearAttachmentPreviews()
        global.URL.createObjectURL = jest.fn(() => 'blob:local-preview')
        global.URL.revokeObjectURL = jest.fn()
    })

    afterEach(() => {
        cleanup()
    })

    it('shows an image as itself, linking to its download', () => {
        render(<ThreadAttachments attachments={[{ name: 'shot.png', ...RESOLVED }]} />)

        const image = screen.getByAltText('shot.png')
        expect(image).toHaveAttribute('src', DOWNLOAD_URL)
        expect(image.closest('a')).toHaveAttribute('href', DOWNLOAD_URL)
    })

    it.each([
        ['a non-image', 'rows.csv', undefined],
        ['an image a comment chip already shows', 'comment-1.png', new Set(['comment-1.png'])],
    ])('shows %s as a badge linking to its download', (_, name, badgeNames) => {
        render(<ThreadAttachments attachments={[{ name, ...RESOLVED }]} badgeNames={badgeNames} />)

        expect(screen.getByText(name).closest('a')).toHaveAttribute('href', DOWNLOAD_URL)
        expect(screen.queryByAltText(name)).not.toBeInTheDocument()
    })

    it('draws the staged file while the upload is still in flight', () => {
        const previewId = rememberAttachmentPreview(new File(['x'], 'shot.png'))

        render(<ThreadAttachments attachments={[{ name: 'shot.png', previewId }]} />)

        expect(screen.getByAltText('shot.png')).toHaveAttribute('src', 'blob:local-preview')
    })

    it('prefers the artifact over the staged file once both are known', () => {
        const previewId = rememberAttachmentPreview(new File(['x'], 'shot.png'))

        render(<ThreadAttachments attachments={[{ name: 'shot.png', previewId, ...RESOLVED }]} />)

        expect(screen.getByAltText('shot.png')).toHaveAttribute('src', DOWNLOAD_URL)
    })

    it('holds the space with a skeleton when an image has neither', () => {
        const { container } = render(<ThreadAttachments attachments={[{ name: 'shot.png' }]} />)

        expect(screen.queryByAltText('shot.png')).not.toBeInTheDocument()
        expect(container.querySelector('.LemonSkeleton')).toBeInTheDocument()
    })

    it('names a pending non-image without offering a download', () => {
        render(<ThreadAttachments attachments={[{ name: 'rows.csv' }]} />)

        expect(screen.getByText('rows.csv').closest('a')).toBeNull()
    })

    it('puts the images above the badges rather than interleaving them', () => {
        const { container } = render(
            <ThreadAttachments
                attachments={[
                    { name: 'rows.csv', ...RESOLVED },
                    { name: 'shot.png', ...RESOLVED },
                ]}
            />
        )

        const rows = container.firstElementChild!.children
        expect(rows).toHaveLength(2)
        expect(rows[0].querySelector('img')).toHaveAttribute('alt', 'shot.png')
        expect(rows[1].textContent).toContain('rows.csv')
    })

    it('moves an image that cannot be fetched down to the badges', () => {
        render(<ThreadAttachments attachments={[{ name: 'shot.png', ...RESOLVED }]} />)
        fireEvent.error(screen.getByAltText('shot.png'))

        expect(screen.queryByAltText('shot.png')).not.toBeInTheDocument()
        expect(screen.getByText('shot.png')).toBeInTheDocument()
    })

    it('renders nothing when a message carried no files', () => {
        const { container } = render(<ThreadAttachments attachments={[]} />)

        expect(container).toBeEmptyDOMElement()
    })
})
