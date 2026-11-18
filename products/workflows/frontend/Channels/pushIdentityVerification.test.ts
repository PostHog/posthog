import { PushIdentityVerificationMode, pushIdentityPublicKeyError } from './pushIdentityVerification'

describe('pushIdentityPublicKeyError', () => {
    const key = '-----BEGIN PUBLIC KEY-----\nabc\n-----END PUBLIC KEY-----'

    it.each<[PushIdentityVerificationMode, string, boolean]>([
        ['disabled', '', false],
        ['optional', '', false],
        ['required', '', true],
        ['required', '   \n', true],
        ['optional', key, false],
        ['required', key, false],
    ])('mode %s with key %j reports an error: %s', (mode, publicKey, hasError) => {
        expect(pushIdentityPublicKeyError(mode, publicKey) !== undefined).toBe(hasError)
    })
})
