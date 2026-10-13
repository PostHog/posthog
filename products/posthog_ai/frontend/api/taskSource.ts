// The icon and label for the product that filed a task, for hosts that only need to name a task's source.
//
// Kept apart from `./primitives` on purpose: the app shell's sidebar imports it, and `./primitives` statically
// pulls the thread presenters and the product data-tool widgets into whatever chunk imports it.
//
// Part of the `products/posthog_ai/frontend/api/<module>` public surface — import from here, not from deep
// `../components/*` paths. See ../README.md for the tier model and ../AGENTS.md for the coupling rule.

export { getOriginProductMeta } from '../components/taskSourceMeta'
export type { OriginProductMeta } from '../components/taskSourceMeta'
