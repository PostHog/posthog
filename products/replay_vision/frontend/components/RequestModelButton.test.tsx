import { fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { preflightLogic } from 'lib/logic/preflightLogic'
import posthog from 'lib/posthog-typed'

import { REQUEST_MODEL_MESSAGE, RequestModelButton } from './RequestModelButton'

jest.mock('lib/posthog-typed', () => ({
    __esModule: true,
    default: { capture: jest.fn() },
}))

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
    useActions: jest.fn(),
}))

const mockedUseValues = useValues as jest.Mock
const mockedUseActions = useActions as jest.Mock
const mockOpenSupportForm = jest.fn()

function setupMocks({ cloud }: { cloud: boolean }): void {
    mockedUseValues.mockImplementation((logic: unknown) => {
        if (logic === preflightLogic) {
            return { preflight: { cloud } }
        }
        throw new Error('unexpected useValues call')
    })
    mockedUseActions.mockImplementation((logic: unknown) => {
        if (logic === supportLogic) {
            return { openSupportForm: mockOpenSupportForm }
        }
        throw new Error('unexpected useActions call')
    })
}

describe('RequestModelButton', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('renders nothing when not on cloud', () => {
        setupMocks({ cloud: false })

        const { container } = render(<RequestModelButton />)

        expect(container.textContent).toBe('')
        expect(mockOpenSupportForm).not.toHaveBeenCalled()
    })

    it('opens the support form prefilled with the model request topic', () => {
        setupMocks({ cloud: true })
        render(<RequestModelButton />)

        fireEvent.click(screen.getByText('Request a model'))

        expect(mockOpenSupportForm).toHaveBeenCalledTimes(1)
        expect(mockOpenSupportForm).toHaveBeenCalledWith({
            kind: 'feedback',
            isEmailFormOpen: true,
            message: REQUEST_MODEL_MESSAGE,
        })
        // The ticket carries only the message, so the topic must be in it.
        expect(REQUEST_MODEL_MESSAGE).toContain('Model request for Replay vision')
        expect(posthog.capture).toHaveBeenCalledWith('replay_vision_model_request_clicked')
    })
})
