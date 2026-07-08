/**
 * Typed errors for signed-state decode failures. Callers (e.g. the
 * confirmed-action runtime) catch by class and map to user-facing messages.
 */

export abstract class SignedStateError extends Error {
    /** Short label suitable for metric/log fields. */
    abstract readonly kind: string
    constructor(message: string) {
        super(message)
        this.name = this.constructor.name
    }
}

export class SignedStateMalformed extends SignedStateError {
    readonly kind = 'malformed'
}
export class SignedStateSignatureInvalid extends SignedStateError {
    readonly kind = 'bad_signature'
}
export class SignedStateExpired extends SignedStateError {
    readonly kind = 'expired'
}
export class SignedStateUserMismatch extends SignedStateError {
    readonly kind = 'user_mismatch'
}
export class SignedStatePurposeMismatch extends SignedStateError {
    readonly kind = 'purpose_mismatch'
}
export class SignedStateAlreadyConsumed extends SignedStateError {
    readonly kind = 'already_consumed'
}
