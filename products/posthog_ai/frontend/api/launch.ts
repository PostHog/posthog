// What a host needs to start a run for the user: the chat's context items and the default model and effort.
// Imports no stream or interaction logic, so a surface that only starts runs, such as the home page, can
// import it eagerly. Load `./logics` with a dynamic import at the moment the host needs `runStreamLogic`.
//
// Part of the `products/posthog_ai/frontend/api/<module>` public surface. See ../README.md for the tier model.

// `chatContextLogic` combines a chat's picks with the rest of its context, and `chatSendItems` is what a
// send path delivers. The picker half (`contextPickerLogic`) is in ./logics.
export { chatContextLogic, chatSendItems } from '../logics/chatContextLogic'

// The standing "act via tool calls" wrapper for a prompt. Its context item is in ./logics.
export { wrapWithPosthogContext } from '../utils/posthogContextBlock'

// The server-resolved default model and effort for this user in this project (their own preference over
// the project default). A host that launches a run on the user's behalf reads it to tell whether a
// stored default will apply, because a model sent with the run overrides one.
export { taskRunDefaultsLogic } from '../logics/taskRunDefaultsLogic'
