import { render, screen } from '@testing-library/react-native'

import { QueuedMessages } from './QueuedMessages'

it('shows delivery progress until an interrupted queue needs review', () => {
    const props = {
        rows: [{ id: 'queued-1', text: 'Check the examples', attachments: [] }],
        held: true,
        notice: 'Check the conversation before sending again.',
        onRemove: jest.fn(),
        onSendNow: jest.fn(),
    }
    const view = render(<QueuedMessages {...props} delivering sendNowPending />)
    expect(screen.getByText('Sending queued messages')).toBeTruthy()
    expect(screen.queryByText(props.notice)).toBeNull()
    expect(screen.getByTestId('chat-queue-send-now')).toBeDisabled()
    view.rerender(<QueuedMessages {...props} delivering={false} sendNowPending={false} />)
    expect(screen.queryByText('Sending queued messages')).toBeNull()
    expect(screen.getByText('1 queued, review before sending')).toBeTruthy()
    expect(screen.getByText(props.notice)).toBeTruthy()
})
