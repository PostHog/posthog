import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { NotificationDestinationTypeEnumApi } from 'products/logs/frontend/generated/api.schemas'

import { LogsAlertDestinationTags } from '../LogsAlertList'

describe('LogsAlertDestinationTags', () => {
    afterEach(() => cleanup())

    it('does not expose Discord as a Logs alert destination', () => {
        render(
            <LogsAlertDestinationTags
                types={[NotificationDestinationTypeEnumApi.Discord, NotificationDestinationTypeEnumApi.Teams]}
            />
        )

        expect(screen.queryByText('Discord')).not.toBeInTheDocument()
        expect(screen.getByText('Teams')).toBeInTheDocument()
    })
})
