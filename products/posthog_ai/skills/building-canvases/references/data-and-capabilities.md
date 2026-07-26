# Data and capabilities

Canvas applications call the host through the injected `ph` runtime:

- `ph.loadInsight(shortId, options)` loads a declared insight.
- `ph.query(query, params)` runs an inline query when `inlineQueries` is enabled.
- `ph.capture(event, properties, distinctId)` captures a declared event name.
- `ph.openExternal(url)` asks the host to open an external URL.
- `ph.navigate.*` asks the host to navigate to a PostHog task or canvas.

Declare the smallest capability set that supports the application:

```json
{
  "posthog": {
    "insights": ["insight-short-id"],
    "inlineQueries": false,
    "captureEvents": ["canvas action"]
  },
  "network": {
    "origins": []
  }
}
```

Direct network origins are disabled until a user-facing capability approval flow exists. The host independently checks
PostHog operations against the manifest. Never embed personal API keys, project tokens, cookies, or other credentials
in source.
