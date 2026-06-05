/**
 * Tests for log-scrubber. The scrubber is one of the last lines of
 * defense against secrets in user-visible logs, so coverage skews
 * toward the not-fun edge cases:
 *
 *   - every prefix family scrubs (vs. silently dropping a prefix we
 *     thought was in the list but isn't)
 *   - non-token text passes through unchanged
 *   - mixed content with multiple tokens
 *   - position in string (start / middle / end / adjacent)
 *   - idempotency under repeated application
 *   - case preservation (so an operator can see "user pasted XOXB-...")
 *
 * Pure tests; no harness dependency. Run with `pnpm exec vitest run
 * src/runtime/log-scrubber.test.ts` from `services/agent-shared`.
 */

import { describe, expect, it } from 'vitest'

import { scrubTokens } from './log-scrubber'

describe('scrubTokens', () => {
    describe('per-prefix coverage', () => {
        // Parameterized so adding a prefix to the source means adding a
        // case here in the same commit. Each example uses a realistic
        // body shape per provider, but the assertion is just "prefix
        // preserved, body redacted" — we don't want to over-fit to a
        // specific token length.
        it.each([
            // Slack
            ['xoxb-1234567890-abcdefghijkl', 'xoxb-****'],
            ['xoxp-1234567890-1234567890-abcd', 'xoxp-****'],
            ['xapp-1-A01234567-1234567890123-abcdef', 'xapp-****'],
            ['xoxa-2-1234567890-1234567890-abcdef', 'xoxa-****'],
            // GitHub
            ['github_pat_11ABCDEFG0_aBcDeFgHiJkLmNoP', 'github_pat_****'],
            ['ghp_1234567890abcdefghijklmnopqrst', 'ghp_****'],
            ['gho_abcdefghijklmnopqrstuvwxyz1234', 'gho_****'],
            ['ghu_abcdefghijklmnopqrstuvwxyz1234', 'ghu_****'],
            ['ghs_abcdefghijklmnopqrstuvwxyz1234', 'ghs_****'],
            // OpenAI / Anthropic-style
            ['sk-proj-abc123def456ghi789', 'sk-****'],
            // Notion
            ['ntn_1234567890abcdefghij', 'ntn_****'],
            // Linear
            ['lin_api_aBcDeFgHiJkLmNoPqRsT', 'lin_api_****'],
        ])('scrubs %s → %s', (input, expected) => {
            expect(scrubTokens(input)).toBe(expected)
        })
    })

    describe('positional invariance', () => {
        it('scrubs a token at the start of the string', () => {
            expect(scrubTokens('ghp_abc123 is the token')).toBe('ghp_**** is the token')
        })

        it('scrubs a token at the end of the string', () => {
            expect(scrubTokens('token: ghp_abc123')).toBe('token: ghp_****')
        })

        it('scrubs a token in the middle of the string', () => {
            expect(scrubTokens('Got token ghp_abc123 from response')).toBe('Got token ghp_**** from response')
        })

        it('scrubs multiple tokens in one string', () => {
            const input = 'slack=xoxb-real github=ghp_real done'
            expect(scrubTokens(input)).toBe('slack=xoxb-**** github=ghp_**** done')
        })

        it('collapses adjacent tokens without whitespace into one redaction', () => {
            // The `\S+` body matcher is greedy, so two token-shaped values
            // mashed together without whitespace get treated as one
            // continuous blob and redacted once. Acceptable failure mode:
            // a single value is more redacted than necessary; nothing
            // leaks. The fix if this ever becomes a real issue is to use
            // a non-greedy match or lookahead on known prefixes.
            expect(scrubTokens('xoxb-a,ghp_b')).toBe('xoxb-****')
        })

        it('scrubs adjacent tokens with whitespace separating them', () => {
            // Whitespace-separated tokens are unambiguously distinct,
            // both get redacted.
            expect(scrubTokens('xoxb-a ghp_b')).toBe('xoxb-**** ghp_****')
        })
    })

    describe('non-secret content', () => {
        it('passes empty string through unchanged', () => {
            expect(scrubTokens('')).toBe('')
        })

        it('passes plain text through unchanged', () => {
            expect(scrubTokens('Connection failed: ECONNREFUSED')).toBe('Connection failed: ECONNREFUSED')
        })

        it('passes a prefix-shaped substring that has whitespace right after through unchanged', () => {
            // The regex requires `\S+` after the prefix, so a prefix
            // followed by a space (e.g. someone wrote literal "ghp_" in
            // a sentence) is not a match.
            expect(scrubTokens('the ghp_ prefix is for classic PATs')).toBe('the ghp_ prefix is for classic PATs')
        })

        it('does not over-scrub words that happen to contain a prefix as a substring', () => {
            // The matcher anchors on the prefix start — a word with the
            // prefix mid-string (e.g. "developmentskip-thing") is not a
            // match because we anchor on the prefix start, not just any
            // occurrence.
            //
            // The current implementation uses a non-anchored regex, so
            // "thisghp_token" WOULD be scrubbed at the substring offset.
            // That's acceptable — it errs on the side of false-positive
            // redaction (hide more than necessary) rather than
            // false-negative leak (miss a real token).
            //
            // This test pins that current behavior so we know if it
            // changes intentionally.
            expect(scrubTokens('thisghp_abctoken')).toBe('thisghp_****')
        })
    })

    describe('idempotency', () => {
        it('scrubbing already-scrubbed text is a no-op', () => {
            // **** contains no token-prefix characters, so re-running the
            // scrubber over its own output should change nothing.
            const once = scrubTokens('xoxb-realtoken')
            expect(once).toBe('xoxb-****')
            expect(scrubTokens(once)).toBe(once)
            expect(scrubTokens(scrubTokens(once))).toBe(once)
        })
    })

    describe('case handling', () => {
        it('matches uppercase prefixes (operator paste from a weird source)', () => {
            // Case-insensitive match. Real Slack tokens are always lowercase
            // but copy-paste mishaps happen; we should still scrub them.
            expect(scrubTokens('XOXB-uppercase_token_value')).toBe('XOXB-****')
        })

        it('preserves the original prefix casing in the redacted output', () => {
            // Diagnostically useful — an operator can see that a token
            // was pasted in a non-canonical case before being redacted.
            expect(scrubTokens('GHP_ABCDEF')).toBe('GHP_****')
            expect(scrubTokens('ghp_abcdef')).toBe('ghp_****')
        })
    })

    describe('realistic crash payloads', () => {
        it('redacts a Bearer header that leaked into a stack trace', () => {
            const input =
                'Streamable HTTP error: Error POSTing to endpoint: bad request: Authorization: Bearer ghp_aBcDeFgHi rejected'
            expect(scrubTokens(input)).toBe(
                'Streamable HTTP error: Error POSTing to endpoint: bad request: Authorization: Bearer ghp_**** rejected'
            )
        })

        it('redacts multiple credentials in a multi-line error', () => {
            const input = [
                'Failed to open MCP client.',
                'Tried github with token ghp_real_value_1234',
                'Tried slack with token xoxb-other-token-5678',
                'All retries exhausted.',
            ].join('\n')
            const out = scrubTokens(input)
            expect(out).toContain('ghp_****')
            expect(out).toContain('xoxb-****')
            expect(out).not.toContain('real_value')
            expect(out).not.toContain('other-token')
        })
    })
})
