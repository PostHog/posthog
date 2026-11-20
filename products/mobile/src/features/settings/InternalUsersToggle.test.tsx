import { fireEvent, render, screen } from '@testing-library/react-native'

import { setAnalyticsClient } from '@/lib/analytics'

import { InternalUsersToggle } from './InternalUsersToggle'
import { useInternalUsersPreference } from './internalUsersPreference'

afterEach(() => {
    setAnalyticsClient(null)
    useInternalUsersPreference.getState().setExclude(false)
})

test('reports each change to the internal user filter with its new state', async () => {
    await useInternalUsersPreference.persist.rehydrate()
    const capture = jest.fn()
    setAnalyticsClient({ capture, identify: jest.fn(), reset: jest.fn() })
    render(<InternalUsersToggle testID="settings-exclude-internal-users" />)
    const toggle = screen.getByTestId('settings-exclude-internal-users')

    fireEvent(toggle, 'valueChange', true)
    fireEvent(toggle, 'valueChange', true)
    fireEvent(toggle, 'valueChange', false)

    expect(capture.mock.calls).toEqual([
        ['mobile_internal_users_filter_changed', { enabled: true }],
        ['mobile_internal_users_filter_changed', { enabled: false }],
    ])
})
