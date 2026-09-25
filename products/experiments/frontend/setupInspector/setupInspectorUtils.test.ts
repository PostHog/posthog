import { CohortPropertyFilter, EventPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import {
    DEFAULT_SETUP_INSPECTOR_INPUTS,
    SetupInspectorInputs,
    canInspectSetupContext,
    toSetupContextInput,
} from './setupInspectorUtils'

describe('setupInspectorUtils', () => {
    test.each([
        { name: 'staff with the flag', isImpersonated: false, superpowersEnabled: true, flagEnabled: true, can: true },
        {
            name: 'staff without the flag',
            isImpersonated: false,
            superpowersEnabled: true,
            flagEnabled: false,
            can: false,
        },
        // The flag also gates the MCP tool, so a customer can have it on. That alone must not show the drawer.
        {
            name: 'customer with the flag',
            isImpersonated: false,
            superpowersEnabled: false,
            flagEnabled: true,
            can: false,
        },
        { name: 'impersonating staff', isImpersonated: true, superpowersEnabled: false, flagEnabled: false, can: true },
    ])('canInspectSetupContext: $name', ({ isImpersonated, superpowersEnabled, flagEnabled, can }) => {
        expect(canInspectSetupContext({ isImpersonated, superpowersEnabled, flagEnabled })).toBe(can)
    })

    const pathnameFilter: EventPropertyFilter = {
        key: '$pathname',
        type: PropertyFilterType.Event,
        operator: PropertyOperator.Exact,
        value: ['/'],
    }
    const cohortFilter: CohortPropertyFilter = {
        key: 'id',
        type: PropertyFilterType.Cohort,
        operator: PropertyOperator.In,
        value: 3,
    }
    const requestCases: { name: string; inputs: Partial<SetupInspectorInputs>; expected: Record<string, unknown> }[] = [
        {
            name: 'drops a URL filter left over from $pageview',
            inputs: { targetEvent: '$screen', targetUrlContains: '/pricing' },
            expected: { target_event: '$screen', target_url_contains: null },
        },
        {
            name: 'drops target filters once the target event is cleared',
            inputs: { targetEvent: null, targetProperties: [pathnameFilter] },
            expected: { target_event: null, target_properties: null },
        },
        {
            name: 'keeps only the filter types the endpoint accepts',
            inputs: {
                targetEvent: '$pageview',
                targetUrlContains: ' /pricing ',
                targetProperties: [pathnameFilter, cohortFilter],
            },
            expected: {
                target_url_contains: '/pricing',
                target_properties: [{ key: '$pathname', type: 'event', operator: 'exact', value: ['/'] }],
            },
        },
    ]

    test.each(requestCases)('toSetupContextInput $name', ({ inputs, expected }) => {
        expect(toSetupContextInput({ ...DEFAULT_SETUP_INSPECTOR_INPUTS, ...inputs })).toMatchObject(expected)
    })
})
