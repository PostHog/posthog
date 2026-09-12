import { authoredCondition, findClockFunction } from './waitClockConditions'

const hogql = (key: string): { key: string; type: string; value: null } => ({ key, type: 'hogql', value: null })

describe('waitClockConditions', () => {
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
            // The parser skips a comment, so a call written around one is still a call.
            ['call split by a comment', 'now/* wall clock */() >= 1', 'now'],
            // An f-string evaluates what sits in its braces.
            ['call inside an f-string', "f'{now()}' > person.properties.label", 'now'],
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
            // The parser reads neither of these as code.
            ['block comment', "person.properties.plan == 'pro' /* now() */"],
            ['line comment', "person.properties.plan == 'pro' -- now()"],
            // The lexer spells a line comment three ways, and skips all of them.
            ['slash line comment', "person.properties.plan == 'pro' // now()"],
            ['hash comment', "person.properties.plan == 'pro' # now()"],
            ['f-string text outside the braces', "f'now() {person.properties.plan}' == 'pro'"],
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

    describe('authoredCondition', () => {
        it('drops compiler output so a save does not make a condition look edited', () => {
            // The API writes bytecode back into the condition it stores, so an unstripped
            // comparison would flag a legacy condition the API still accepts.
            const filters = { properties: [hogql('now() >= 1')] }

            expect(authoredCondition({ filters: { ...filters, bytecode: ['_H', 1], source: 'x' } as any })).toEqual(
                authoredCondition({ filters })
            )
        })
    })
})
