/**
 * At-rest encryption for the personal API key, using Electron's safeStorage
 * (Keychain on macOS, DPAPI on Windows, kwallet/libsecret on Linux). On Linux
 * systems without a secret store the key falls back to plaintext-on-disk with
 * a warning, mirroring what Chromium itself does for cookies.
 */

import { safeStorage } from 'electron'

const ENCRYPTED_PREFIX = 'v1:'
const PLAIN_PREFIX = 'plain:'

export function encryptSecret(secret: string): string {
    if (safeStorage.isEncryptionAvailable()) {
        return ENCRYPTED_PREFIX + safeStorage.encryptString(secret).toString('base64')
    }
    console.warn('OS secret storage is unavailable; storing the API key without encryption')
    return PLAIN_PREFIX + Buffer.from(secret, 'utf8').toString('base64')
}

export function decryptSecret(stored: string): string | null {
    try {
        if (stored.startsWith(ENCRYPTED_PREFIX)) {
            return safeStorage.decryptString(Buffer.from(stored.slice(ENCRYPTED_PREFIX.length), 'base64'))
        }
        if (stored.startsWith(PLAIN_PREFIX)) {
            return Buffer.from(stored.slice(PLAIN_PREFIX.length), 'base64').toString('utf8')
        }
        return null
    } catch (error) {
        console.error('Could not decrypt the stored API key', error)
        return null
    }
}
