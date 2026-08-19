import { BREAKDOWN_PRESETS } from './Breakdowns/consts'
import { BUILT_IN_ERROR_TRACKING_PROPERTIES, resolveBuiltInProperty } from './builtInProperties'

describe('built-in error tracking properties', () => {
    const operatingSystem = BUILT_IN_ERROR_TRACKING_PROPERTIES.find(({ title }) => title === 'Operating system')!

    // getExceptionAttributes prefers $os_name, so this has to prefer it too. Otherwise one exception
    // reports a different platform in the properties table than in the release popover.
    it.each([
        ['both keys are set', { $os_name: 'iPadOS', $os: 'Mac OS X' }, '$os_name'],
        ['only $os_name is set', { $os_name: 'Android' }, '$os_name'],
        ['only $os is set', { $os: 'Windows' }, '$os'],
        ['$os_name is empty', { $os_name: '', $os: 'Windows' }, '$os'],
        ['neither key is set', {}, '$os'],
    ])('reads the operating system from $os_name first when %s', (_name, properties, expected) => {
        expect(resolveBuiltInProperty(properties, operatingSystem)).toEqual(expected)
    })

    // Breakdowns match on `property`, so moving the OS entry onto $os_name would drop this preset
    // and reclassify an $os breakdown as a custom property.
    it('keeps $os as the canonical operating system key for breakdown presets', () => {
        expect(BREAKDOWN_PRESETS).toContainEqual({ property: '$os', title: 'Operating system' })
    })
})
