import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { SignalReportArtefact } from '../../types'
import { ArtefactLogList } from './ArtefactLogList'

function makeArtefact(content: Record<string, any>, type = 'implementation_decision'): SignalReportArtefact {
    return {
        id: 'artefact-1',
        type,
        content,
        created_at: '2026-06-11T10:00:00Z',
    }
}

describe('ArtefactLogList', () => {
    afterEach(() => {
        cleanup()
    })

    it.each([
        ['a replacement recommendation', true, 'Replacement recommended'],
        ['a kept PR', false, 'Still the right fix'],
    ])('shows the decision and its reason for %s', (_name, supersede, expectedTag) => {
        render(
            <ArtefactLogList
                reportId="report-1"
                artefacts={[makeArtefact({ supersede, reason: 'The root cause moved to the ingestion path.' })]}
            />
        )

        expect(screen.getByText('Open PR assessed')).toBeInTheDocument()
        expect(screen.queryByText('implementation_decision')).not.toBeInTheDocument()
        expect(screen.getByText(expectedTag)).toBeInTheDocument()
        expect(screen.getByText('The root cause moved to the ingestion path.')).toBeInTheDocument()
    })

    it('links the selected predecessors when a replacement starts', () => {
        const oldPr = 'https://github.com/example/repo/pull/1'
        render(
            <ArtefactLogList
                reportId="report-1"
                artefacts={[makeArtefact({ decision: { targets: [{ pr_url: oldPr }] } }, 'implementation_replacement')]}
            />
        )
        expect(screen.getByText('Replacement started')).toBeInTheDocument()
        expect(screen.getByText(oldPr).closest('a')).toHaveAttribute('href', oldPr)
        expect(screen.queryByText('Replaced')).not.toBeInTheDocument()
    })

    it('shows the replacement and individual outcomes without exposing internal retry records', () => {
        const oldPr = 'https://github.com/example/repo/pull/1'
        const keptPr = 'https://github.com/example/repo/pull/2'
        const newPr = 'https://github.com/example/repo/pull/3'
        render(
            <ArtefactLogList
                reportId="report-1"
                artefacts={[
                    {
                        ...makeArtefact(
                            { status: 'processing', explanation: 'Internal lease' },
                            'implementation_handover'
                        ),
                        id: 'retry',
                    },
                    makeArtefact(
                        {
                            status: 'needs_attention',
                            explanation: 'Review the remaining PRs.',
                            replacement_pr_urls: [newPr],
                            results: { [oldPr]: 'closed', [keptPr]: 'skipped' },
                        },
                        'implementation_handover'
                    ),
                ]}
            />
        )
        for (const url of [oldPr, keptPr, newPr]) {
            expect(screen.getByText(url).closest('a')).toHaveAttribute('href', url)
        }
        expect(screen.getByText(/Not closed by PostHog/)).toBeInTheDocument()
        expect(screen.queryByText('Internal lease')).not.toBeInTheDocument()
    })
})
