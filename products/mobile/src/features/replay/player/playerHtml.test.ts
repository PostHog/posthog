import { blockChunkScript, parsePlayerMessage, playerHtml } from './playerHtml'

test.each([
    ['{"type":"block","id":1,"index":0}', { type: 'block', id: 1, index: 0 }],
    ['{"type":"block","id":1,"index":2}', null],
    ['{"type":"block","id":1,"index":-1}', null],
    ['{"type":"block","id":1,"index":"0"}', null],
    ['{"type":"block","id":1.5,"index":0}', null],
    ['{"type":"block","id":0,"index":0}', null],
    ['{"type":"block","id":10000,"index":1}', { type: 'block', id: 10000, index: 1 }],
    ['{"type":"block","id":10001,"index":0}', null],
    ['{"type":"block","id":1,"index":0.5}', null],
    ['{"type":"fetch","url":"https://example.com"}', null],
    ['{"type":"ready"}', { type: 'ready' }],
    ['invalid', null],
])('only accepts bounded recording block requests: %s', (input, expected) => {
    expect(parsePlayerMessage(input, 2)).toEqual(expected)
})

test('customer text stays data when sent into the player and cannot end the setup script', () => {
    const value = '</script><script>window.leaked=true</script>\n"\\'
    expect(blockChunkScript(1, value, true)).not.toContain('</script>')
    const html = playerHtml(
        { sessionId: value, seconds: 0, startTimestamp: null, blockCount: 1, replayProxyToken: null },
        { background: '#fff', ink: '#000', border: '#eee' },
        'test-nonce'
    )
    expect(html).not.toContain('<script>window.leaked')
    expect(html).toContain("connect-src 'none'")
    expect(html).toContain('sandbox')
})
