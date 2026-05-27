/**
 * Per-session nonce broker. Custom tools receive opaque nonces, never raw
 * secret values. At egress, the proxy substitutes nonces back to values.
 *
 * Lifetime is session-scoped: nonces expire when the sandbox is released.
 */

import { randomBytes } from 'crypto'

export class SecretBroker {
    private readonly bySession = new Map<string, Map<string, string>>() // session -> nonce -> value
    private readonly reverseBySession = new Map<string, Map<string, string>>() // session -> secretName -> nonce

    mintSessionMap(sessionId: string, secrets: Record<string, string>): Record<string, string> {
        const nonceToValue = new Map<string, string>()
        const nameToNonce = new Map<string, string>()
        const out: Record<string, string> = {}
        for (const [name, value] of Object.entries(secrets)) {
            const nonce = `nonce_${randomBytes(16).toString('hex')}`
            nonceToValue.set(nonce, value)
            nameToNonce.set(name, nonce)
            out[name] = nonce
        }
        this.bySession.set(sessionId, nonceToValue)
        this.reverseBySession.set(sessionId, nameToNonce)
        return out
    }

    /** Replace any nonce occurrences in `text` with the real value for `sessionId`. */
    substitute(sessionId: string, text: string): string {
        const map = this.bySession.get(sessionId)
        if (!map) {
            return text
        }
        let out = text
        for (const [nonce, value] of map.entries()) {
            if (out.includes(nonce)) {
                out = out.split(nonce).join(value)
            }
        }
        return out
    }

    /** Scrub raw secret values from text — for output redaction. */
    scrub(sessionId: string, text: string): string {
        const map = this.bySession.get(sessionId)
        if (!map) {
            return text
        }
        let out = text
        for (const value of map.values()) {
            if (value && out.includes(value)) {
                out = out.split(value).join('[REDACTED]')
            }
        }
        return out
    }

    release(sessionId: string): void {
        this.bySession.delete(sessionId)
        this.reverseBySession.delete(sessionId)
    }
}
