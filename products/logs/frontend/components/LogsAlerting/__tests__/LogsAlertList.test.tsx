import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { NotificationDestinationTypeEnumApi } from 'products/logs/frontend/generated/api.schemas'

import { LogsAlertDestinationTags } from '../LogsAlertList'

describe('LogsAlertDestinationTags', () => {
    afterEach(() => cleanup())

    it('renders Discord separately from Microsoft Teams', () => {
        render(
            <LogsAlertDestinationTags
                types={[NotificationDestinationTypeEnumApi.Discord, NotificationDestinationTypeEnumApi.Teams]}
            />
        )

        expect(screen.getByText('Discord')).toBeInTheDocument()
        expect(screen.getByText('Teams')).toBeInTheDocument()
    })
})
