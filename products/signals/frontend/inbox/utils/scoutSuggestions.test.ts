import type { ScoutSuggestionItemApi, SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'

import { suggestionToCreateValues } from './scoutSuggestions'

describe('suggestionToCreateValues', () => {
    it("carries an existing scout's repositories and write access into the form", () => {
        // Turning an existing scout on PATCHes the whole form back, so a field the mapper leaves
        // out is submitted as its empty default and the scout loses it.
        const item = {
            id: 'suggestion-1',
            skill_name: 'signals-scout-foo',
            description: 'proposed',
            draft_body: 'body',
            proposed_config: { run_cron_schedule: null, run_interval_minutes: null, emit: true },
        } as unknown as ScoutSuggestionItemApi
        const config = {
            id: 'config-1',
            emit: false,
            output_destinations: {},
            tags: ['billing'],
            mcp_gateway_server_ids: ['11111111-1111-1111-1111-111111111111'],
            repositories: ['acme-co/app', 'acme-co/docs'],
            write_scopes: ['dashboard:write'],
            run_cron_schedule: '30 9 * * *',
            run_interval_minutes: 1440,
        } as unknown as SignalScoutConfigApi

        const values = suggestionToCreateValues(item, { config, description: 'existing', body: 'existing body' })

        expect(values.existingConfigId).toBe('config-1')
        expect(values.config).toMatchObject({
            emit: false,
            tags: ['billing'],
            mcp_gateway_server_ids: ['11111111-1111-1111-1111-111111111111'],
            repositories: ['acme-co/app', 'acme-co/docs'],
            write_scopes: ['dashboard:write'],
            run_cron_schedule: '30 9 * * *',
        })
    })
})
