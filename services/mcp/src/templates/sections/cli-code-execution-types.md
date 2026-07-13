### Code execution (`types` / `sql`)

```text
types <query>                                # search SDK methods/types; signatures scope-annotated for this token
types <TypeName... | domain.method | domain> # exact names (space-separated for several) return full TS declarations
sql <hogql>                                  # run HogQL directly (rest of command, may span lines)
```

`types` picks its mode by exactness: exact tokens return those declarations, with references as fetch hints; anything else is a search. Output is char-capped — truncations name the follow-up `types` call, so never guess a cut-off declaration.
