# Hog evaluation code examples

Hog evaluations run deterministic code against each generation.
The code must return a boolean (`true` = pass, `false` = fail).
Use `print()` to add reasoning — printed output is captured as the evaluation reasoning.

## Available globals

| Global              | Type   | Description                                                                             |
| ------------------- | ------ | --------------------------------------------------------------------------------------- |
| `input`             | string | LLM input — always a string (objects are JSON-serialized; use `jsonParse()` if needed)  |
| `output`            | string | LLM output — always a string (objects are JSON-serialized; use `jsonParse()` if needed) |
| `properties`        | object | All event properties (access any `$ai_*` property)                                      |
| `event.uuid`        | string | Event UUID                                                                              |
| `event.event`       | string | Event name                                                                              |
| `event.distinct_id` | string | Distinct ID                                                                             |

## Important Hog syntax notes

- Use **single quotes** for strings: `'hello'` not `"hello"`
- Use `length()` not `len()`
- Use `ifNull(value, default)` before comparing properties that might be null — null comparisons throw runtime errors
- `return null` means N/A (only when `allows_na` is enabled on the evaluation)

## Examples

### Check output length

```hog
let len := length(output)
if (len < 10) {
    print('Output too short:', len, 'characters')
    return false
}
if (len > 5000) {
    print('Output too long:', len, 'characters')
    return false
}
return true
```

### Check for required keywords

```hog
let out := lower(output)
if (not like(out, '%sorry%') and not like(out, '%unfortunately%')) {
    if (like(out, '%error%') or like(out, '%failed%')) {
        print('Error response missing apology')
        return false
    }
}
return true
```

### Cost threshold check

```hog
let cost := ifNull(toFloat(properties.$ai_total_cost_usd), 0)
if (cost > 0.10) {
    print('Generation cost too high: $', cost)
    return false
}
return true
```

### Token limit check

```hog
let output_tokens := ifNull(toInt(properties.$ai_output_tokens), 0)
if (output_tokens > 2000) {
    print('Too many output tokens:', output_tokens)
    return false
}
return true
```

### Skip non-applicable generations (return N/A)

Requires `allows_na: true` on the evaluation.

```hog
let model := ifNull(properties.$ai_model, '')
if (not like(model, '%gpt%')) {
    print('Skipping non-GPT model:', model)
    return null
}
let out := lower(output)
if (like(out, '%harmful%') or like(out, '%dangerous%')) {
    print('Potentially harmful content detected')
    return false
}
return true
```

### Check JSON output format

```hog
let out := trim(output)
if (not like(out, '{%')) {
    print('Output is not JSON — starts with:', left(out, 20))
    return false
}
print('Output appears to be JSON')
return true
```
