import { Agent, setGlobalDispatcher } from 'undici'

/**
 * Routes global `fetch` through this package's undici instead of the copy bundled with Node.
 *
 * Node 24.22.1 bundles undici 7.30.1. When a `Connection: close` response ends while backpressure
 * has paused the HTTP/1 parser, that version throws `assert(!this.paused)` from the socket 'end'
 * handler, and the throw exits the process (nodejs/undici#5360). undici 8.6.0 and later finish
 * the paused parser instead. Remove this module when the Node release in services/mcp/Dockerfile
 * bundles an undici 7.x that contains nodejs/undici#5553.
 *
 * `allowH2: false` keeps HTTP/1.1, the protocol the bundled dispatcher uses, because undici 8
 * offers HTTP/2 over ALPN by default.
 */
export function installHttpDispatcher(): void {
    setGlobalDispatcher(new Agent({ allowH2: false }))
}
