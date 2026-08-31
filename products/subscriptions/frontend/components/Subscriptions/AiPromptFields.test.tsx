import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'

import { AiPromptFields } from './AiPromptFields'

jest.mock('lib/lemon-ui/LemonField', () => ({
    LemonField: ({ label, children }: { label?: ReactNode; children?: ReactNode }) => (
        <div>
            {label}
            {typeof children === 'function' ? null : children}
        </div>
    ),
}))

describe('AiPromptFields', () => {
    it('asks for the team goal without adding a second goal field', () => {
        render(
            <AiPromptFields
                contexts={[]}
                contextsEnabled={false}
                prompt=""
                windowMode="since_last_sent"
                onAddContext={jest.fn()}
                onRemoveContext={jest.fn()}
                onSelectAnalysisWindow={jest.fn()}
                onSelectExample={jest.fn()}
            />
        )

        expect(screen.getByText('What goal should this report help your team achieve?')).toBeInTheDocument()
        expect(screen.queryByText('What do you want to know?')).not.toBeInTheDocument()
    })
})
