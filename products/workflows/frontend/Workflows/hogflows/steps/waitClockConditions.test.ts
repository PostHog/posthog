import { findClockFunction } from './waitClockConditions'

const hogql = (key: string): { key: string; type: string; value: null } => ({ key, type: 'hogql', value: null })

describe('findClockFunction', () => {
    it.each([
        ['now comparison', 'now() >= toDateTime(person.properties.expires_at)', 'now'],
        ['unix wrapped', 'toUnixTimestamp(now()) >= toUnixTimestamp(person.properties.expires_at)', 'now'],
        ['date diff', "dateDiff('day', toDateTime(person.properties.last_seen_at), now()) >= 14", 'now'],
        ['today', 'today() >= toDate(person.properties.expires_at)', 'today'],
        ['nested in arithmetic', 'person.properties.count > toUnixTimestamp(now()) - 86400', 'now'],
        // One clock term is enough to make the whole condition unwakeable, so an AND must not
        // launder it past the check.
        ['anded with a person property', "person.properties.plan == 'pro' and now() >= 1", 'now'],
        ['spaced call', 'now () >= 1', 'now'],
    ])('finds the clock function in a %s', (_name, expression, expected) => {
        expect(findClockFunction({ properties: [hogql(expression)] })).toBe(expected)
    })

    it.each([
        ['person property', "person.properties.plan == 'enterprise'"],
        ['fixed date comparison', "toDateTime(person.properties.expires_at) > toDateTime('2026-01-01')"],
        // A word that merely ends in a clock function name is not a call to one.
        ['similarly named function', 'snow(person.properties.depth) > 1'],
        // Nor is a property of that name.
        ['property called now', 'person.properties.now > 1'],
        // The check must not read inside a string literal, where any text is allowed.
        ['quoted literal', "person.properties.label == 'now()'"],
    ])('accepts a %s', (_name, expression) => {
        expect(findClockFunction({ properties: [hogql(expression)] })).toBeNull()
    })

    it('ignores a non-HogQL filter whose key reads like a call', () => {
        expect(findClockFunction({ properties: [{ key: 'now()', type: 'person', value: 'x' }] })).toBeNull()
    })

    it('finds a clock function nested in an event entry of the condition', () => {
        // The API accepts a condition with event entries, so an agent-authored flow can carry one.
        expect(findClockFunction({ events: [{ properties: [hogql('now() > 1')] }] })).toBe('now')
    })

    it('returns null for an empty condition', () => {
        expect(findClockFunction(null)).toBeNull()
    })
})
