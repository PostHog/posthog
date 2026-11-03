import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { SentryMigrationItemApi, SentryProjectApi } from '../../../generated/api.schemas'
import { sentryMigrationLogic } from './sentryMigrationLogic'

const PROJECT: SentryProjectApi = {
    organization_slug: 'acme',
    organization_name: 'Acme',
    project_slug: 'web',
    project_name: 'Web',
    platform: 'javascript',
    region_url: null,
}

function item(id: string, overrides: Partial<SentryMigrationItemApi> = {}): SentryMigrationItemApi {
    return {
        id,
        category: 'release',
        sentry_setting: 'Release filter',
        sentry_value: '1.0.*',
        fit: 'good',
        note: null,
        suppression_rule_filters: { type: 'AND', values: [] },
        rate_limit: null,
        built_in_filter: null,
        already_in_posthog: false,
        limits_other_client_keys: false,
        ...overrides,
    }
}

const ITEMS = [item('release:1'), item('release:2')]

describe('sentryMigrationLogic', () => {
    let logic: ReturnType<typeof sentryMigrationLogic.build>

    beforeEach(async () => {
        useMocks({
            post: {
                '/api/environments/:team_id/error_tracking/sentry_migration/projects/': { projects: [PROJECT] },
                '/api/environments/:team_id/error_tracking/sentry_migration/preview/': { items: ITEMS },
            },
        })
        initKeaTests()
        logic = sentryMigrationLogic()
        logic.mount()
        logic.actions.setAuthToken('not-a-real-token')
        await expectLogic(logic, () => logic.actions.loadProjects()).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.selectProject('acme/web')).toFinishAllListeners()
    })

    it.each([
        ['starting over', () => logic.actions.resetWizard()],
        ['connecting again', () => logic.actions.loadProjects()],
    ])('clears the previous preview when %s', (_name, action) => {
        action()

        expect(logic.values).toMatchObject({ selectedProjectKey: null, items: null, selectedItemIds: [] })
    })

    it('keeps the settings the user left out when an import refreshes the preview', () => {
        logic.actions.setSelectedItemIds(['release:1'])

        logic.actions.loadPreviewSuccess([item('release:1', { already_in_posthog: true }), item('release:2')], {
            keepSelection: true,
        })

        expect(logic.values.selectedItemIds).toEqual([])
    })

    it('names the inbound filters it leaves out of the list', async () => {
        const ipFilter = item('inbound_filter:blocked-ips', {
            category: 'inbound_filter',
            fit: 'unsupported',
            sentry_setting: 'IP address filter',
        })
        useMocks({
            post: {
                '/api/environments/:team_id/error_tracking/sentry_migration/preview/': {
                    items: [item('release:1'), ipFilter],
                },
            },
        })

        await expectLogic(logic, () => logic.actions.loadPreview()).toFinishAllListeners()

        expect(logic.values).toMatchObject({ items: [item('release:1')], omittedFilterNames: ['IP address filter'] })
    })

    it('loads the preview again when the import fails because Sentry changed', async () => {
        useMocks({
            post: {
                '/api/environments/:team_id/error_tracking/sentry_migration/apply/': () => [
                    400,
                    { detail: 'Some selected settings changed in Sentry since the preview. Load the preview again.' },
                ],
                '/api/environments/:team_id/error_tracking/sentry_migration/preview/': { items: [item('release:1')] },
            },
        })
        logic.actions.setSelectedItemIds(['release:1', 'release:2'])

        await expectLogic(logic, () => logic.actions.applyImport()).toFinishAllListeners()

        expect(logic.values).toMatchObject({ items: [item('release:1')], selectedItemIds: ['release:1'] })
    })
})
