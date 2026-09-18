# Minimal survey drafts

These inputs use `posthog:survey-create` and omit `start_date` so they stay drafts.
Adapt the questions to the request. Verify any event names and audience rules
against the project before adding them.

## In-app NPS

```json
{
  "name": "Product recommendation feedback",
  "type": "popover",
  "questions": [
    {
      "type": "rating",
      "question": "How likely are you to recommend this product?",
      "display": "number",
      "scale": 10
    },
    {
      "type": "open",
      "question": "What is the main reason for your score?",
      "optional": true
    }
  ]
}
```

This has no audience restriction. Add the user's intended display conditions
and targeting before launch. For CSAT, use a satisfaction question and scale 5.

## Hosted feedback form

```json
{
  "name": "Product feedback form",
  "type": "external_survey",
  "questions": [
    {
      "type": "open",
      "question": "What could make this product easier to use?"
    }
  ]
}
```

Hosted forms do not need a URL display condition, cohort, or linked feature flag.
Only enable iframe embedding when requested.

## Headless feedback form

```json
{
  "name": "In-app feedback definition",
  "type": "api",
  "questions": [
    {
      "type": "open",
      "question": "What would you like us to improve?"
    }
  ]
}
```

The application must render this form and capture the survey's events. Use the
returned survey and question IDs in that implementation; do not invent them.
