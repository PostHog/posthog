import { render } from '@testing-library/react'

import { PatternTemplate } from './LogsPatterns'

describe('PatternTemplate', () => {
    it.each([
        ['literal tags', 'render <div> for <customer>', []],
        [
            'body placeholders',
            'at <timestamp> <klogtime> <uuid> <ip> <version> <host> <hex> <num> <*>',
            ['<timestamp>', '<klogtime>', '<uuid>', '<ip>', '<version>', '<host>', '<hex>', '<num>', '<*>'],
        ],
        [
            'stored placeholders',
            '<N> <TIMESTAMP> <KLOGTIME> <UUID> <IP> <HOST> <HEX> <ID> <EMAIL> <JSON_ARRAY>',
            [
                '<N>',
                '<TIMESTAMP>',
                '<KLOGTIME>',
                '<UUID>',
                '<IP>',
                '<HOST>',
                '<HEX>',
                '<ID>',
                '<EMAIL>',
                '<JSON_ARRAY>',
            ],
        ],
        ['JSON key set', '<JSON:foo,bar,+2> and <JSON:>', ['<JSON:foo,bar,+2>', '<JSON:>']],
        ['masked JSON keys', 'keys <JSON:account_<ID>,<UUID>,name,+2> <div>', ['<JSON:account_<ID>,<UUID>,name,+2>']],
    ])('highlights only supported tokens: %s', (_name, pattern, expected) => {
        const { container } = render(<PatternTemplate pattern={pattern as string} />)
        expect(container.textContent).toBe(pattern)
        expect(Array.from(container.querySelectorAll('.text-accent'), (token) => token.textContent)).toEqual(expected)
    })
})
