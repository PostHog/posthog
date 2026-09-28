# Reputation action list

Each row type of the action list is one `defineReputationAction` file in `actions/definitions/`.
The rest of `actions/` is what they share: types, context, ranking, buttons and the registry.
To add a row type:

- Add its kind to `ReputationActionKind`. Kinds are pinned, because the buttons' `data-attr` carries them.
- Register the action in `REPUTATION_ACTIONS` under its kind. The typecheck fails on a kind with no action, and `reputationActionRegistry.test.ts` fails on an action that is not registered under its own kind.
- Pick its place in the order from `SLOT_ORDER` in `reputationActionRanking.ts`. Add a slot there if none fits.
