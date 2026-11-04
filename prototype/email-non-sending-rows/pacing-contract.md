# Pacing contract sketch (option B)

Not compiled, not wired.

```ts
// Sketch of the seam option B adds. Not compiled, not wired.

export type PacedSlot = { kind: 'now' } | { kind: 'booked'; sendAt: Date; bucketKey: string }

export interface WorkflowEmailPacing {
  // Called once per send, when the hogflow worker routes it to the email queue.
  // A booked slot has its token already debited, so the send must not claim again.
  // Invariant: slots for one bucket are handed out one refill interval apart, in call order.
  // Fail-closed: when Valkey errors, returns a short retry slot that is not booked.
  book(teamId: number, workflowId: string, limit: { count: number; period: 'minute' | 'hour' }): Promise<PacedSlot>
}

// Limiter side, replacing the reservation that is "a place in line, not a promise":
// the deny path advances the bucket's next-free time (GCRA-style) and returns it,
// so the booked caller owns that token.
export interface PrepaidClaim {
  claimOrBook(key: string, capacity: number, refillPerSecond: number): Promise<{ sendAt: number | null }>
}
```
