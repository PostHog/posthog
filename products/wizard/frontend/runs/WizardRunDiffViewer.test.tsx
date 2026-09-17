import '@testing-library/jest-dom'

import { parsePatchFiles } from '@pierre/diffs'
import type { FileDiffMetadata } from '@pierre/diffs'
import { cleanup, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { WizardRunDiffViewer } from './WizardRunDiffViewer'

// @pierre/diffs ships ESM-only, which Jest cannot resolve — stub both entry points.
jest.mock('@pierre/diffs', () => ({ parsePatchFiles: jest.fn() }), { virtual: true })
jest.mock('@pierre/diffs/react', () => ({ FileDiff: () => null }), { virtual: true })

const mockParsePatchFiles = jest.mocked(parsePatchFiles)

function makeFile(overrides: Partial<FileDiffMetadata> = {}): FileDiffMetadata {
    return {
        name: 'src/app.ts',
        type: 'change',
        hunks: [],
        splitLineCount: 0,
        unifiedLineCount: 0,
        isPartial: true,
        deletionLines: [],
        additionLines: [],
        ...overrides,
    }
}

describe('WizardRunDiffViewer', () => {
    beforeEach(() => {
        initKeaTests()
        mockParsePatchFiles.mockReset()
    })

    afterEach(cleanup)

    it('renders file cards for a well-formed diff', () => {
        mockParsePatchFiles.mockReturnValue([{ files: [makeFile({ unifiedLineCount: 4 })] }])

        render(<WizardRunDiffViewer diff="patch" contentHash="hash-1" sizeBytes={512} pullRequestUrl={null} />)

        expect(screen.getByText('src/app.ts')).toBeInTheDocument()
    })

    it('shows an error banner instead of an empty result for a malformed diff', () => {
        mockParsePatchFiles.mockImplementation(() => {
            throw new Error('malformed patch')
        })

        render(
            <WizardRunDiffViewer
                diff="not a valid patch"
                contentHash="hash-2"
                sizeBytes={512}
                pullRequestUrl="https://github.com/posthog/posthog/pull/1"
            />
        )

        expect(screen.getByText(/Couldn't display this diff/)).toBeInTheDocument()
        expect(screen.getByText(/Open the pull request/)).toBeInTheDocument()
    })

    it('describes a mode-only change instead of rendering zero lines', () => {
        mockParsePatchFiles.mockReturnValue([{ files: [makeFile({ prevMode: '100644', mode: '100755' })] }])

        render(<WizardRunDiffViewer diff="patch" contentHash="hash-3" sizeBytes={512} pullRequestUrl={null} />)

        expect(screen.getByText(/File mode changed from 100644 to 100755/)).toBeInTheDocument()
    })

    it('describes a binary change instead of rendering zero lines', () => {
        mockParsePatchFiles.mockReturnValue([{ files: [makeFile({ name: 'assets/logo.png' })] }])

        render(<WizardRunDiffViewer diff="patch" contentHash="hash-4" sizeBytes={512} pullRequestUrl={null} />)

        expect(screen.getByText(/Binary file changed/)).toBeInTheDocument()
    })

    it('does not promise a pull request when there is none', () => {
        mockParsePatchFiles.mockImplementation(() => {
            throw new Error('malformed patch')
        })

        render(
            <WizardRunDiffViewer diff="not a valid patch" contentHash="hash-5" sizeBytes={512} pullRequestUrl={null} />
        )

        expect(screen.queryByText(/Open the pull request/)).not.toBeInTheDocument()
    })
})
