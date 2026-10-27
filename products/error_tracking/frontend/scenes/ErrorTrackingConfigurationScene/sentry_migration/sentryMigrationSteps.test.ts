import type { SentryMigrationCategoryEnumApi, SentryMigrationItemApi } from '../../../generated/api.schemas'
import { wizardSteps } from './sentryMigrationSteps'

function item(category: SentryMigrationCategoryEnumApi): SentryMigrationItemApi {
    return {
        id: `${category}:1`,
        category,
        sentry_setting: 'Setting',
        sentry_value: 'On',
        fit: 'good',
        note: null,
        suppression_rule_filters: null,
        rate_limit: null,
        built_in_filter: null,
        already_in_posthog: false,
    }
}

describe('sentryMigrationSteps', () => {
    it.each([
        ['before a project loads', null, ['source', 'location', 'token', 'project']],
        ['for a project with nothing to import', [], ['source', 'location', 'token', 'project']],
        [
            'with one step per section the project has, in a fixed order',
            [item('inbound_filter'), item('error_message')],
            ['source', 'location', 'token', 'project', 'error_messages', 'inbound_filters', 'review'],
        ],
    ])('lists the steps %s', (_name, items, expected) => {
        expect(wizardSteps(items).map((step) => step.key)).toEqual(expected)
    })
})
