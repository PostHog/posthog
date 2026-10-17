// The server's refresh windows (`next_allowed_client_refresh`, `cache_target_age`) are server times. A phone clock
// that runs fast would force a compute inside the window, so every comparison with them goes through `serverNow()`.

let offsetMs = 0

/**
 * Keeps the offset between the server's `Date` header and the device clock from the latest response. A missing or
 * unreadable header keeps the previous offset, so the device clock applies until a server sends one.
 */
export function recordServerDate(header: string | null | undefined, receivedAt: number = Date.now()): void {
    if (!header) {
        return
    }
    const server = Date.parse(header)
    if (Number.isNaN(server)) {
        return
    }
    offsetMs = server - receivedAt
}

export function serverOffsetMs(): number {
    return offsetMs
}

/** Epoch ms in server time. */
export function serverNow(): number {
    return Date.now() + offsetMs
}

export function resetServerClock(): void {
    offsetMs = 0
}
