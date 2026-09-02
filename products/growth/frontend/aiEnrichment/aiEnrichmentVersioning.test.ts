import type { ConfigVersionApi } from '../generated/api.schemas'
import { suggestNextVersion } from './aiEnrichmentVersioning'

const version = (version: string): ConfigVersionApi =>
    ({
        version,
    }) as ConfigVersionApi

describe('suggestNextVersion', () => {
    it('suggests v1 for a label with no versions yet', () => {
        expect(suggestNextVersion([])).toBe('v1')
    })

    it('bumps the highest numbered suffix, not the version count', () => {
        expect(suggestNextVersion([version('v1'), version('v2'), version('v3')])).toBe('v4')
    })

    it('ignores gaps left by a deleted version and never reuses a retired string', () => {
        expect(suggestNextVersion([version('v1'), version('v3')])).toBe('v4')
    })

    it('finds a v<n> suffix anywhere in a legacy-named version, not just an exact v<n> match', () => {
        expect(suggestNextVersion([version('ai-pilled-clay-v1')])).toBe('v2')
        expect(suggestNextVersion([version('ai-pilled-clay-v1'), version('ai-pilled-v2-draft')])).toBe('v3')
    })

    it('falls back to one past the version count when nothing has a numeric v suffix at all', () => {
        expect(suggestNextVersion([version('alpha'), version('beta')])).toBe('v3')
    })
})
