import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { fireEvent } from '@testing-library/react'

import { projectLogic } from 'scenes/projectLogic'

import { initKeaTests } from '~/test/init'

import { ThreadAttachments } from './ThreadAttachments'

const RESOLVED = { taskId: 'task-3', runId: 'run-7', artifactId: 'art-9' }
const DOWNLOAD_URL = '/api/projects/997/tasks/task-3/runs/run-7/artifacts/art-9/download/'

describe('ThreadAttachments', () => {
    beforeEach(() => {
        initKeaTests()
        projectLogic.mount()
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

    it('shows anything else as a chip linking to its download', () => {
        render(<ThreadAttachments attachments={[{ name: 'rows.csv', ...RESOLVED }]} />)

        expect(screen.getByText('rows.csv').closest('a')).toHaveAttribute('href', DOWNLOAD_URL)
        expect(screen.queryByAltText('rows.csv')).not.toBeInTheDocument()
    })

    it('holds the space with a skeleton while an image has no artifact yet', () => {
        const { container } = render(<ThreadAttachments attachments={[{ name: 'shot.png' }]} />)

        expect(screen.queryByAltText('shot.png')).not.toBeInTheDocument()
        expect(container.querySelector('.LemonSkeleton')).toBeInTheDocument()
    })

    it('names a pending non-image without offering a download', () => {
        render(<ThreadAttachments attachments={[{ name: 'rows.csv' }]} />)

        expect(screen.getByText('rows.csv').closest('a')).toBeNull()
    })

    it('falls back to a chip when the image cannot load', () => {
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
