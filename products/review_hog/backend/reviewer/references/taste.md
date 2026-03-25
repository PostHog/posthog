# PostHog Product Taste

These are the principles that should inform the "taste check" in a product review. They come from PostHog's own writing — James Hawkins, the handbook, and the team's published thinking on what makes good product.

## The core tension

PostHog optimizes for **speed and autonomy over polish and control**. Engineers ship without waiting for design approval. This is intentional and good — but it means taste issues can slip through because there's no design gate. The product review is one of the few moments where someone asks "does this feel right?" before it ships.

## What taste looks like at PostHog

### Controls should communicate how they work

A button should look like a button. A toggle should look like a toggle. Radio buttons mean "pick one", checkboxes mean "pick many." If a user has to think about what a control does, the affordance is wrong. ("An affordance is the way an object communicates how it works." — Danilo Campos)

### Match existing product patterns

PostHog has a design system. If the rest of the product scopes preferences per-project, a new feature shouldn't store them globally. If existing wizards have 3 steps, a new one with 7 steps needs justification. Consistency reduces the burden of understanding — pattern-breaking needs a reason.

### Don't add modes when you can show things inline

Every mode (toggle, tab, view switcher) is a fork in the user's attention. If something can be shown directly without a mode switch, do that instead. Modes hide information and create state that users have to track mentally.

### Defaults should be right for most people

If a user has to immediately change a setting to get the right experience, the default is wrong. The first thing a user sees should be the thing most users want. Configuration is for power users, not for compensating for bad defaults.

### Eliminate jank, not features

Jank is misaligned elements, inconsistent spacing, typography that doesn't follow hierarchy, too many colors without meaning. Jank signals carelessness. But the fix for jank is fixing the jank, not removing the feature. Ship fast, then tighten up.

### Complexity should earn its place

Every new step in a wizard, every new option in a dropdown, every new setting — these all add cognitive load. They need to justify their existence with clear user value. If you can't explain why a user would want this option, it probably shouldn't be there.

### If it needs docs to explain, the UX might be wrong

"Thinner docs, better products." If a feature requires extensive documentation or tooltips for users to understand it, that's a signal the design itself could be simpler. The product should communicate how it works through its interface, not through help text bolted on afterward.

### Features should feel integrated, not bolted on

A new capability should feel like it belongs in the product — using the same patterns, the same visual language, the same interaction models. If it feels like a separate thing sitting next to the product rather than part of it, it needs more integration work. "Assistants are what you build when intelligence sits next to your product. Systems are what you build when intelligence becomes part of it."

### Minimal is fine, confusing is not

PostHog ships rough v0.1s on purpose — "many new features are so simple they can verge on embarrassing." A feature being minimal doesn't mean it lacks taste. But minimal and confusing are different things. A v0.1 with three buttons that clearly communicate what they do has taste. A v0.1 with three buttons where you can't tell what any of them do is janky.

## How to apply this in a review

Don't nitpick design details — that's not the point. Look for one of these specific patterns:

1. **Broken consistency** — this feature works differently from how the same pattern works elsewhere in the product. Example: "Every other preference is scoped to the project. This one is global."

2. **Wrong default** — the first thing users see isn't what most users want. They have to configure their way to the right experience.

3. **Unnecessary modes** — a toggle, tab, or view switch that could be eliminated by just showing the information directly.

4. **Confusing affordances** — a control that doesn't communicate what it does. A button that looks like a link. A destructive action that doesn't look destructive.

5. **Bolted-on feel** — a feature that feels like it was added next to the product rather than integrated into it. Uses different patterns, different interaction models, or feels like a separate tool.

6. **Docs-dependent UX** — the feature only makes sense if you read the documentation first. The interface itself doesn't communicate what it does or how it works.

If none of these apply, say nothing about taste. A PR that's consistent, has good defaults, and uses clear affordances doesn't need a taste note — it has taste. And remember: a minimal v0.1 is not a taste problem. Confusing is a taste problem.
