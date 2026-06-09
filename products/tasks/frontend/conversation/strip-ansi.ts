/**
 * Dependency-free ANSI escape-sequence stripper.
 *
 * Console output and shell command results in the transcript may carry ANSI
 * color / cursor control codes. We render them as plain text, so strip the
 * escape sequences before display.
 */

// CSI / SGR sequences (colors, cursor moves) plus standalone OSC sequences.
const ANSI_PATTERN = new RegExp(
    [
        '[\\u001B\\u009B][[\\]()#;?]*(?:(?:(?:[a-zA-Z\\d]*(?:;[a-zA-Z\\d]*)*)?\\u0007)',
        '(?:(?:\\d{1,4}(?:;\\d{0,4})*)?[\\dA-PR-TXZcf-nq-uy=><~]))',
    ].join('|'),
    'g'
)

export function stripAnsi(s: string): string {
    if (typeof s !== 'string') {
        return String(s)
    }
    return s.replace(ANSI_PATTERN, '')
}
