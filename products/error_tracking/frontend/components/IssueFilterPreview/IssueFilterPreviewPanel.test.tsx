import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import type { ReactElement, ReactNode } from 'react'

import { initKeaTests } from '~/test/init'

import { IssueFilterPreviewPanel } from './IssueFilterPreviewPanel'

const mockUseActions = jest.fn()
const mockUseValues = jest.fn()

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useActions: (...args: unknown[]) => mockUseActions(...args),
    useValues: (...args: unknown[]) => mockUseValues(...args),
}))

jest.mock('lib/hooks/useFeatureFlag', () => ({
    useFeatureFlag: () => false,
}))

jest.mock('../Breakdowns/MiniBreakdowns', () => ({
    MiniBreakdowns: () => <div>Breakdown preview</div>,
}))

jest.mock('../FingerprintPreview/FingerprintPreview', () => ({
    FingerprintPreview: () => <div>Fingerprint preview</div>,
}))

jest.mock('../IssueReleases/IssueReleasesPreview', () => ({
    IssueReleasesPreview: () => <div>Releases preview</div>,
}))

jest.mock('./TimeFilterPreview', () => ({
    TimeFilterPreview: () => <div>Time preview</div>,
}))

jest.mock('lib/ui/quill', () => ({
    ...jest.requireActual('lib/ui/quill'),
    Tooltip: ({ children }: { children: ReactNode }) => <>{children}</>,
    TooltipContent: () => null,
    TooltipTrigger: ({ render }: { render: ReactElement }) => render,
}))

describe('IssueFilterPreviewPanel', () => {
    beforeEach(() => {
        initKeaTests()
        mockUseActions.mockReturnValue({ setActivePreview: jest.fn() })
        mockUseValues
            .mockReturnValueOnce({ activePreview: 'fingerprints' })
            .mockReturnValueOnce({ issueId: 'test-issue' })
    })

    it('shows the fingerprint tab and content without feature flags', () => {
        render(<IssueFilterPreviewPanel>Issue events</IssueFilterPreviewPanel>)

        expect(screen.getByLabelText('Fingerprints')).toBeInTheDocument()
        expect(screen.getByText('Fingerprint preview')).toBeInTheDocument()
    })
})
