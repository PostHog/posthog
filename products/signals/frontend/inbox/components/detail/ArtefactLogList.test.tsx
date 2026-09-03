import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { SignalReportArtefact } from '../../types'
import { ArtefactLogList } from './ArtefactLogList'

function makeArtefact(content: Record<string, any>): SignalReportArtefact {
    return {
        id: 'artefact-1',
        type: 'implementation_decision',
        content,
        created_at: '2026-06-11T10:00:00Z',
    }
}

describe('ArtefactLogList', () => {
    afterEach(() => {
        cleanup()
    })

    it.each([
        ['a replaced PR', true, 'Replaced'],
        ['a kept PR', false, 'Still the right fix'],
    ])('shows the decision and its reason for %s', (_name, supersede, expectedTag) => {
        render(
            <ArtefactLogList
                reportId="report-1"
                artefacts={[makeArtefact({ supersede, reason: 'The root cause moved to the ingestion path.' })]}
            />
        )

        // The row used to read `implementation_decision` with an empty body, because the default
        // body case looks for a `content` key this payload does not have.
        expect(screen.getByText('Open PR assessed')).toBeInTheDocument()
        expect(screen.queryByText('implementation_decision')).not.toBeInTheDocument()
        expect(screen.getByText(expectedTag)).toBeInTheDocument()
        expect(screen.getByText('The root cause moved to the ingestion path.')).toBeInTheDocument()
    })
})
