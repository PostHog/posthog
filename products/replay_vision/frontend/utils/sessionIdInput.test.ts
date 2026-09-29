import { sessionIdFromInput } from './sessionIdInput'

describe('sessionIdFromInput', () => {
    test.each([
        ['a bare ID', '01966b3f-70a1-7c52-a4d5-3f9b2e8c1d07', '01966b3f-70a1-7c52-a4d5-3f9b2e8c1d07'],
        ['a bare ID with whitespace', '  abc123  ', 'abc123'],
        ['a recording link', 'https://us.example.com/project/2/replay/abc123', 'abc123'],
        ['a recording link with a timestamp', 'https://us.example.com/project/2/replay/abc123?t=42', 'abc123'],
        ['a relative recording path', '/project/2/replay/abc123', 'abc123'],
        [
            'a replay list link with a selected recording',
            'https://us.example.com/project/2/replay/home?sessionRecordingId=abc123',
            'abc123',
        ],
        ['a replay list link with nothing selected', 'https://us.example.com/project/2/replay/home', null],
        ['a playlist link', 'https://us.example.com/project/2/replay/playlists/xyz', null],
        ['a link to some other page', 'https://us.example.com/project/2/insights/abc', null],
        ['a link with broken percent-encoding', '/project/2/replay/abc%E0%A4%A', null],
        ['nothing', '   ', null],
    ])('%s', (_name, input, expected) => {
        expect(sessionIdFromInput(input)).toBe(expected)
    })
})
