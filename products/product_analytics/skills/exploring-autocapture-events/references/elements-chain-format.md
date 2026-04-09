# elements_chain format

The `elements_chain` column stores the clicked DOM element and its ancestors as a single string.

## Structure

```text
tag_name.class1.class2:key1="value1":key2="value2";parent_tag.parent_class:key="val"
```

- Elements are separated by `;` (semicolons)
- First element is the clicked element, subsequent elements are ancestors up the DOM tree
- Each element starts with `tag_name` optionally followed by `.class` segments (sorted alphabetically)
- After the tag/class portion, key-value attributes follow as `:key="value"` pairs
- Quotes within values are escaped as `\"`

## Standard attribute keys

| Key           | Description                                       |
| ------------- | ------------------------------------------------- |
| `text`        | Inner text content of the element                 |
| `href`        | Link href attribute                               |
| `attr_id`     | HTML id attribute                                 |
| `nth-child`   | Position among siblings                           |
| `nth-of-type` | Position among siblings of the same type          |
| `attr_class`  | CSS classes (also encoded in the `.class` prefix) |

## Custom attributes

Custom DOM attributes appear verbatim in the chain.
The most useful for analytics are `data-*` attributes:

- `data-attr` — PostHog's default data attribute (configurable per team)
- `data-testid` — common testing attribute, also useful for analytics
- `aria-label` — accessibility label, sometimes useful as a selector

Example chain with a data-attr:

```text
button.btn.primary:data-attr="checkout":text="Buy Now";div.container:attr_id="main"
```

## How CSS selectors map to regex

PostHog converts CSS selectors to regex patterns matched against `elements_chain`:

- `button` → `(^|;)button(\.|$|;|:)`
- `button.cta` → `(^|;)button.*?cta.*?`
- `#submit` → uses `indexOf(elements_chain_ids, 'submit') > 0` (optimized)
- `[data-attr="checkout"]` → `(^|;).*?data-attr="checkout".*?`
- `button[data-attr="checkout"]` → `(^|;)button.*?data-attr="checkout".*?`

In HogQL, use `elements_chain =~ '{regex}'` for matching.
