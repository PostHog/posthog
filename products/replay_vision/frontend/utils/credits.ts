import { humanFriendlyCurrency } from 'lib/utils/numbers'

/** 1 credit = $0.01; all quota amounts arrive from the API as credits and render as dollars. */
export const CREDITS_PER_DOLLAR = 100

export function formatCredits(credits: number): string {
    return humanFriendlyCurrency(credits / CREDITS_PER_DOLLAR)
}
