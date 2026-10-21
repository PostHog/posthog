import assert from 'node:assert/strict'
import { channel } from 'node:diagnostics_channel'
import { once } from 'node:events'
import { createServer } from 'node:net'

const socketEnded = new Promise((resolve) => {
    channel('undici:client:connected').subscribe(({ socket }) => socket.once('end', resolve))
})
const body = Buffer.alloc(64 * 1024, 'a')
const server = createServer((socket) => {
    socket.once('data', () => {
        socket.end(
            Buffer.concat([
                Buffer.from(
                    'HTTP/1.1 200 OK\r\nContent-Length: ' + body.length + '\r\nConnection: close\r\n\r\n'
                ),
                body,
            ])
        )
    })
})
server.listen(0, '127.0.0.1')
await once(server, 'listening')

try {
    const request = new Request('http://127.0.0.1:' + server.address().port)
    const response = await fetch(request)
    await socketEnded
    assert(response instanceof Response)
    assert(response.headers instanceof Headers)
    assert.equal(await response.text(), body.toString())
    console.info('response complete')
} finally {
    server.close()
}
