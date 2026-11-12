import { render, screen } from '@testing-library/react-native'
import type { ReactElement } from 'react'
import { Text } from 'react-native'

import { useAuthStore } from '@/auth/authStore'
import { useProjectScope } from '@/auth/useProjectScope'

import { ExperimentLinkScope } from './ExperimentLinkScope'

jest.mock('@/demo/demoMode', () => ({ useDataMode: () => 'live' }))
jest.mock('@/features/views/screen/ViewChrome', () => ({ ViewChrome: () => null }))
jest.mock('@/features/views/screen/ViewScreenFrame', () => ({ useViewBack: () => jest.fn() }))

function Scope(): ReactElement {
    const scope = useProjectScope()
    return <Text testID="scope">{`${scope?.host}|${scope?.projectId}`}</Text>
}

describe('experiment link scope', () => {
    beforeEach(() => {
        useAuthStore.setState({ signedIn: true, host: 'https://app.example.com:8443', projectId: 2 })
    })

    it('loads the linked project without changing the session project', () => {
        render(
            <ExperimentLinkScope project="7" host="app.example.com:8443">
                <Scope />
            </ExperimentLinkScope>
        )
        expect(screen.getByTestId('scope').props.children).toBe('https://app.example.com:8443|7')
        expect(useAuthStore.getState().projectId).toBe(2)
    })

    it.each(['other.example.com:8443', 'app.example.com:9443'])('does not load experiment content on %s', (host) => {
        render(
            <ExperimentLinkScope project="7" host={host}>
                <Scope />
            </ExperimentLinkScope>
        )
        expect(screen.queryByTestId('scope')).toBeNull()
        expect(screen.getByTestId('experiment-elsewhere')).toBeTruthy()
    })
})
