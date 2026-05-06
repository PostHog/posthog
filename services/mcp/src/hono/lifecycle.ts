// Mutable pod state shared with request handlers. `/readyz` returns 503 once
// `shuttingDown` flips so kube-proxy evicts us; the streamable handler refuses
// new sessions for the same reason. Active sessions keep working until they
// finish or the drain budget elapses.
export type Lifecycle = { shuttingDown: boolean }

export const newLifecycle = (): Lifecycle => ({ shuttingDown: false })
