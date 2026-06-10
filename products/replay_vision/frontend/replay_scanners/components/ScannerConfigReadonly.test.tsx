import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'

import { NodeKind } from '~/queries/schema/schema-general'

import { ClassifierScanner, MonitorScanner, ReplayScanner, ScorerScanner, SummarizerScanner } from '../types'
import { ScannerConfigReadonly } from './ScannerConfigReadonly'

function baseScanner(): Omit<ReplayScanner, 'scanner_type' | 'scanner_config'> {
    return {
        id: 'abc-123',
        name: 'Test scanner',
        description: 'Watches for X.',
        enabled: true,
        sampling_rate: 0.5,
        query: { kind: NodeKind.RecordingsQuery },
        provider: 'google',
        model: 'gemini-3-flash-preview',
        emits_signals: false,
        scanner_version: 1,
        last_swept_at: '2026-01-01T00:00:00Z',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        created_by: null,
    }
}

describe('ScannerConfigReadonly', () => {
    it('renders the Overview, Behavior, and Triggers & runtime cards with shared fields', () => {
        const scanner: MonitorScanner = {
            ...baseScanner(),
            scanner_type: 'monitor',
            scanner_config: { prompt: 'Did the user struggle?' },
        }
        render(<ScannerConfigReadonly scanner={scanner} />)
        expect(screen.getByText('Overview')).toBeInTheDocument()
        expect(screen.getByText('Behavior')).toBeInTheDocument()
        expect(screen.getByText('Triggers & runtime')).toBeInTheDocument()
        expect(screen.getByText('Did the user struggle?')).toBeInTheDocument()
        expect(screen.getByText('Watches for X.')).toBeInTheDocument()
        expect(screen.getByText('50%')).toBeInTheDocument()
    })

    it('renders Allow inconclusive verdicts for monitor scanners', () => {
        const scanner: MonitorScanner = {
            ...baseScanner(),
            scanner_type: 'monitor',
            scanner_config: { prompt: 'Q?', allow_inconclusive: true },
        }
        render(<ScannerConfigReadonly scanner={scanner} />)
        expect(screen.getAllByText('Allow inconclusive verdicts').length).toBeGreaterThan(0)
        expect(screen.getAllByText('Yes').length).toBeGreaterThan(0)
    })

    it('renders Summary length for summarizer scanners', () => {
        const scanner: SummarizerScanner = {
            ...baseScanner(),
            scanner_type: 'summarizer',
            scanner_config: { prompt: 'Summarize.', length: 'short' },
        }
        render(<ScannerConfigReadonly scanner={scanner} />)
        expect(screen.getByText('Summary length')).toBeInTheDocument()
        expect(screen.getByText('short')).toBeInTheDocument()
    })

    it('renders tag vocabulary + multi-label + freeform for classifier scanners', () => {
        const scanner: ClassifierScanner = {
            ...baseScanner(),
            scanner_type: 'classifier',
            scanner_config: {
                prompt: 'Tag.',
                tags: ['bug', 'frustration'],
                multi_label: true,
                allow_freeform_tags: false,
            },
        }
        render(<ScannerConfigReadonly scanner={scanner} />)
        expect(screen.getByText('Tag vocabulary')).toBeInTheDocument()
        expect(screen.getByText('bug')).toBeInTheDocument()
        expect(screen.getByText('frustration')).toBeInTheDocument()
        expect(screen.getByText('Multiple tags per session')).toBeInTheDocument()
        expect(screen.getByText('Freeform tags')).toBeInTheDocument()
    })

    it('renders the configured scale for scorer scanners', () => {
        const scanner: ScorerScanner = {
            ...baseScanner(),
            scanner_type: 'scorer',
            scanner_config: { prompt: 'Score.', scale: { min: 0, max: 10, label: 'frustration' } },
        }
        render(<ScannerConfigReadonly scanner={scanner} />)
        expect(screen.getAllByText('Scale').length).toBeGreaterThan(0)
        expect(screen.getAllByText(/0 – 10/).length).toBeGreaterThan(0)
        expect(screen.getAllByText(/frustration/).length).toBeGreaterThan(0)
    })

    it('falls back to "All completed recordings" when no recording filters are configured', () => {
        const scanner: MonitorScanner = {
            ...baseScanner(),
            scanner_type: 'monitor',
            scanner_config: { prompt: 'Q?' },
        }
        render(<ScannerConfigReadonly scanner={scanner} />)
        expect(screen.getAllByText('All completed recordings').length).toBeGreaterThan(0)
    })
})
