import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { router } from 'kea-router'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { sourceWizardLogic } from 'products/data_warehouse/frontend/scenes/NewSourceScene/sourceWizardLogic'
import type { SourceConfigResponseApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { DataSourceSetup } from './DataSourceSetup'

const INTERCOM_CONFIG: SourceConfigResponseApi = {
    name: 'Intercom',
    iconPath: '',
    caption: null,
    supportsColumnSelection: false,
    versions: [],
    defaultVersion: '',
    deprecatedVersions: [],
    fields: [
        {
            type: 'oauth',
            name: 'intercom_integration_id',
            label: 'Intercom workspace',
            required: true,
            kind: 'intercom',
        },
    ],
}

describe('DataSourceSetup', () => {
    afterEach(cleanup)

    it('adopts the OAuth account in the resumed signal form without losing required tables or completion', async () => {
        initKeaTests()
        useMocks({
            get: {
                '/api/projects/:team_id/external_data_sources/wizard/': { Intercom: INTERCOM_CONFIG },
                '/api/projects/:team_id/integrations/': {
                    results: [
                        { id: 7, kind: 'intercom', display_name: 'Example workspace', user_access_level: 'manager' },
                    ],
                    next: null,
                },
            },
        })
        router.actions.push('/inbox', { setup: 'signal-sources', signal_source: 'intercom', integration_id: '7' })
        const onComplete = jest.fn()
        render(
            <DataSourceSetup
                source="intercom"
                onComplete={onComplete}
                oauthRedirectUrl="/inbox?setup=signal-sources&signal_source=intercom"
            />
        )

        await screen.findByText('Intercom workspace')
        await waitFor(() =>
            expect(sourceWizardLogic.values.sourceConnectionDetails.payload.intercom_integration_id).toBe(7)
        )
        expect(sourceWizardLogic.values.requiredTables).toEqual(['conversations'])
        expect(sourceWizardLogic.props.onComplete).toBe(onComplete)
        expect(sourceWizardLogic.values.oauthRedirectUrl).toContain('signal_source=intercom')
        expect(router.values.searchParams.integration_id).toBeUndefined()
    })
})
