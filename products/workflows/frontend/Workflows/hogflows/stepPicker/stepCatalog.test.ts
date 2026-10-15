import { FEATURE_FLAGS } from 'lib/constants'
import { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import { STEP_ATTRIBUTION } from './stepAttribution'
import { StepCatalogEntry, StepCatalogInput, buildStepCatalog } from './stepCatalog'
import { ALL_STEP_IDS, DESTINATION_TEMPLATES, destination } from './stepCatalogTestTemplates'

const ALL_FLAGS_ON: FeatureFlagsSet = {
    [FEATURE_FLAGS.WORKFLOWS_PUSH_NOTIFICATIONS]: true,
    [FEATURE_FLAGS.WORKFLOW_AI_TASK_ACTION]: true,
    [FEATURE_FLAGS.WORKFLOW_RUN_SCOUT_ACTION]: true,
    [FEATURE_FLAGS.WORKFLOW_CLASSIFY_ACTION]: true,
    [FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP]: true,
    [FEATURE_FLAGS.CUSTOMER_ANALYTICS_CUSTOMER_TASKS]: true,
}

const FULL_INPUT: StepCatalogInput = {
    featureFlags: ALL_FLAGS_ON,
    isMainEnvironment: true,
    isRowScopedTrigger: false,
    destinationTemplates: DESTINATION_TEMPLATES,
}

const BUILT_IN_AND_REGISTERED_IDS = ALL_STEP_IDS.slice(0, ALL_STEP_IDS.indexOf('template-activecampaign'))

const catalogIds = (input: Partial<StepCatalogInput>): string[] =>
    buildStepCatalog({ ...FULL_INPUT, ...input }).map((entry) => entry.id)

const entryById = (entries: StepCatalogEntry[], id: string): StepCatalogEntry | undefined =>
    entries.find((entry) => entry.id === id)

describe('buildStepCatalog', () => {
    it('lists every step the picker can add with all flags on in the main environment', () => {
        expect(catalogIds({})).toEqual(ALL_STEP_IDS)
    })

    it.each<[string, Partial<StepCatalogInput>, string[]]>([
        [
            'all flags off',
            { featureFlags: {} },
            [
                'template-native-push',
                'template-posthog-create-task',
                'template-posthog-run-scout',
                'template-posthog-classify',
                'template-posthog-create-customer-task',
                'template-posthog-create-account',
                'template-posthog-get-account',
                'template-posthog-tag-account',
                'template-posthog-update-account-relationships',
                'template-posthog-update-account-property',
            ],
        ],
        [
            'customer tasks flag off',
            { featureFlags: { ...ALL_FLAGS_ON, [FEATURE_FLAGS.CUSTOMER_ANALYTICS_CUSTOMER_TASKS]: false } },
            ['template-posthog-create-customer-task'],
        ],
        ['not the main environment', { isMainEnvironment: false }, ['template-posthog-run-scout']],
        [
            'a row-scoped trigger',
            { isRowScopedTrigger: true },
            ['step-wait_until_condition', 'step-random_cohort_branch'],
        ],
    ])('leaves out the ineligible steps with %s', (_name, input, removedIds) => {
        expect(catalogIds(input)).toEqual(ALL_STEP_IDS.filter((id) => !removedIds.includes(id)))
    })

    it('lists only built-in and registered steps while destination templates load', () => {
        expect(catalogIds({ destinationTemplates: null })).toEqual(BUILT_IN_AND_REGISTERED_IDS)
    })

    it('has attribution for every built-in and registered step', () => {
        const unattributed = BUILT_IN_AND_REGISTERED_IDS.filter((id) => !(id in STEP_ATTRIBUTION))
        expect(unattributed).toEqual([])
    })

    it.each([
        [
            'template-posthog-create-task',
            FEATURE_FLAGS.WORKFLOW_AI_TASK_ACTION,
            {
                config: {
                    template_id: 'template-posthog-create-task',
                    inputs: { non_failure_status_codes: { value: [409] } },
                },
                output_variable: { key: 'task', result_path: null, label: 'Task' },
            },
        ],
        [
            'template-posthog-run-scout',
            FEATURE_FLAGS.WORKFLOW_RUN_SCOUT_ACTION,
            {
                config: {
                    template_id: 'template-posthog-run-scout',
                    inputs: { non_failure_status_codes: { value: [409] } },
                },
                output_variable: { key: 'scout_run', result_path: null, label: 'Scout run' },
            },
        ],
        [
            'template-posthog-classify',
            FEATURE_FLAGS.WORKFLOW_CLASSIFY_ACTION,
            {
                config: { template_id: 'template-posthog-classify', inputs: {} },
                output_variable: [
                    { key: 'category', result_path: 'category', label: 'Category' },
                    { key: 'confidence', result_path: 'confidence', label: 'Confidence' },
                ],
            },
        ],
    ])(
        'keeps the special config of %s and takes the tags of a destination template with the same ID',
        (id, flag, expectedAction) => {
            const offeredTemplate = destination(id, 'Offered as a destination', ['Custom'])

            const flagOn = buildStepCatalog({ ...FULL_INPUT, destinationTemplates: [offeredTemplate] })
            expect(flagOn.filter((entry) => entry.id === id)).toEqual([
                expect.objectContaining({ action: expect.objectContaining(expectedAction), tags: ['Custom'] }),
            ])

            const flagOff = buildStepCatalog({
                ...FULL_INPUT,
                featureFlags: { ...ALL_FLAGS_ON, [flag]: false },
                destinationTemplates: [offeredTemplate],
            })
            expect(entryById(flagOff, id)).toBeUndefined()
        }
    )

    it.each<[string, string[], StepCatalogEntry['category'], StepCatalogEntry['status']]>([
        ['a mapped tag', ['Customer Success', 'CRM'], 'crm', null],
        ['no tags', [], null, null],
        ['only unmapped tags', ['Custom'], null, 'beta'],
    ])('lists an unknown destination with %s as a third-party step', (_name, tags, category, status) => {
        const template = destination('template-acme', 'Acme', tags, { status: status ?? 'stable' })

        const entry = entryById(buildStepCatalog({ ...FULL_INPUT, destinationTemplates: [template] }), 'template-acme')

        expect(entry).toEqual({
            id: 'template-acme',
            action: {
                type: 'function',
                name: 'Acme',
                description: 'Acme destination',
                config: { template_id: 'template-acme', inputs: {} },
            },
            name: 'Acme',
            operation: null,
            description: 'Acme destination',
            origin: 'third_party',
            product: null,
            vendor: 'Acme',
            category,
            tags,
            status,
        })
    })

    it('labels the operations of vendors with several steps', () => {
        const operationsByVendor: Record<string, (string | null)[]> = {}
        for (const entry of buildStepCatalog(FULL_INPUT)) {
            if (entry.vendor) {
                operationsByVendor[entry.vendor] = [...(operationsByVendor[entry.vendor] ?? []), entry.operation]
            }
        }

        expect(Object.fromEntries(Object.entries(operationsByVendor).filter(([, ops]) => ops.length > 1))).toEqual({
            Google: ['Ads conversions', 'Cloud Storage', 'Pub/Sub'],
            HubSpot: ['Create contact', 'Create company', 'Send event'],
            Intercom: ['Update contact', 'Send event'],
            Klaviyo: ['Send event', 'Update contact'],
            Loops: ['Update contact', 'Send event'],
            Mailjet: ['Add contact', 'Update contact list'],
            Salesforce: ['Create object', 'Look up object', 'Update object'],
        })
    })

    it.each([
        ['template-posthog-create-task', 'posthog', 'tasks', null],
        ['template-posthog-send-ticket-message', 'posthog', 'support', null],
        ['template-twilio', 'third_party', null, 'Twilio'],
        ['template-posthog-replicator', 'posthog', 'core', null],
    ])('attributes %s to its origin, product and vendor', (id, origin, product, vendor) => {
        expect(entryById(buildStepCatalog(FULL_INPUT), id)).toMatchObject({ origin, product, vendor })
    })
})
