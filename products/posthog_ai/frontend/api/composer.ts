// Tier 2 — the Composer compound and the quill composer frame, without the thread.
//
// LIGHT boundary: eager surfaces that only need an input box (the today home ask box) import from here.
// ./primitives also re-exports the thread presenters, and their static imports pull the whole query and
// insight stack onto the importer's eager path.
//
// Part of the `products/posthog_ai/frontend/api/<module>` public surface — import from here, not from
// deep `../components/*` paths. See ../README.md for the tier model and ../AGENTS.md for the coupling rule.

export { Composer } from '../components/composer/Composer'
export type {
    ComposerRootProps,
    ComposerFrameProps,
    ComposerTextareaProps,
    ComposerSubmitProps,
} from '../components/composer/Composer'

// The quill composer frame (bordered input group with an inline send button) and its send button.
export { QuillComposerLayout } from '../components/quill/QuillComposerLayout'
export type { QuillComposerLayoutProps } from '../components/quill/QuillComposerLayout'
export { QuillComposerSendButton } from '../components/quill/QuillComposerSendButton'
