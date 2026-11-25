# meep-policy

A topic asks before running an action unless a rule decides otherwise. When several rules apply, the last one wins. Inbox skip rules are written in natural language. `skip_candidates` limits them by connection and channel before the engine asks System One which apply.

## Decide whether to send a reply

```rust
use meep_policy::{decide, Verdict};
use meep_topic::{Action, ActionKind};

let reply = Action {
    kind: ActionKind("slack-reply".into()),
    label: "Send reply".into(),
    done_label: "Sent reply".into(),
    payload: Default::default(),
    depends_on_facts: Some(vec![]),
};
assert_eq!(decide(&[], &reply), Verdict::Ask(None));
```

The optimistic command path uses the same action verdict and approval-rule builder as the server. An approval with “always” records the rule under the ID supplied by the person's command.
