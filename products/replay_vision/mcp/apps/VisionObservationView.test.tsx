import { cleanup, render, screen } from '@testing-library/react'
import { type ReactElement } from 'react'

import { VisionObservationView, observationHeadline } from './VisionObservationView'

jest.mock(
    '@posthog/mcp-ui',
    () => ({
        DescriptionList: ({ items }: { items: { label: string; value: string }[] }): ReactElement => (
            <dl>
                {items.map((item) => (
                    <div key={item.label}>
                        <dt>{item.label}</dt>
                        <dd>{item.value}</dd>
                    </div>
                ))}
            </dl>
        ),
    }),
    { virtual: true }
)

jest.mock(
    '@posthog/quill',
    () => ({
        Badge: ({ children }: { children: ReactElement }): ReactElement => <span>{children}</span>,
        Card: ({ children }: { children: ReactElement }): ReactElement => <div>{children}</div>,
        CardContent: ({ children }: { children: ReactElement }): ReactElement => <div>{children}</div>,
    }),
    { virtual: true }
)

describe('VisionObservationView', () => {
    afterEach(cleanup)

    // The scanner type decides which output fields exist, and the list shows one line per row. A bare
    // monitor verdict ("yes") reads as nothing, so reasoning has to win when both are present.
    it.each([
        ['summarizer', { title: 'Abandoned checkout', summary: 'They gave up.' }, 'Abandoned checkout'],
        ['summarizer without a title', { summary: 'They gave up.' }, 'They gave up.'],
        ['monitor', { verdict: 'yes', reasoning: 'Never reached signup.' }, 'Never reached signup.'],
        ['monitor without reasoning', { verdict: 'yes' }, 'yes'],
        ['a finished scan with no output', null, 'No result'],
    ])('takes the headline from %s output', (_name, modelOutput, expected) => {
        const headline = observationHeadline({
            id: 'obs-1',
            session_id: 'session-1',
            status: 'succeeded',
            scanner_result: modelOutput ? { model_output: modelOutput } : null,
        })

        expect(headline).toBe(expected)
    })

    it('shows why a recording could not be watched', () => {
        render(
            <VisionObservationView
                data={{
                    id: 'obs-2',
                    session_id: 'session-2',
                    status: 'ineligible',
                    error_reason: 'too_short:the recording is under five seconds long',
                    scanner_result: null,
                }}
            />
        )

        expect(screen.getByText('the recording is under five seconds long')).toBeTruthy()
    })

    it('renders the summary body for a summarizer result', () => {
        render(
            <VisionObservationView
                data={{
                    id: 'obs-3',
                    session_id: 'session-3',
                    status: 'succeeded',
                    scanner_result: { model_output: { title: 'Abandoned checkout', summary: 'They gave up.' } },
                }}
            />
        )

        expect(screen.getByText('Abandoned checkout')).toBeTruthy()
        expect(screen.getByText('They gave up.')).toBeTruthy()
    })
})
