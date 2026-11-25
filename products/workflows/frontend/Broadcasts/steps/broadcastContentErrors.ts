const MISSING_CONTENT_ERRORS = ['Choose an email sender', 'Add a subject line', 'Add email content']

export function isMissingContentError(error: string): boolean {
    return MISSING_CONTENT_ERRORS.includes(error)
}

/** "Choose an email sender and add a subject line": the steps still to do, as one sentence. */
export function missingContentReason(errors: string[]): string | undefined {
    const missing = errors.filter(isMissingContentError)
    if (!missing.length || missing.length !== errors.length) {
        return undefined
    }
    const lowered = missing.map((error, index) => (index === 0 ? error : error[0].toLowerCase() + error.slice(1)))
    return lowered.length > 1 ? `${lowered.slice(0, -1).join(', ')} and ${lowered[lowered.length - 1]}` : lowered[0]
}
