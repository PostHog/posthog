# Surveys

## Survey (`system.surveys`)

Surveys collect feedback from users through questions and forms.

### Columns

The `system.surveys` HogQL view exposes a deliberately narrow set of columns — these are exactly what `SELECT *` returns:

Column | Type | Nullable | Description
`id` | integer | NOT NULL | Primary key (auto-generated)
`team_id` | integer | NOT NULL | Owning team
`name` | varchar(400) | NOT NULL | Survey name (unique per team)
`type` | varchar(40) | NOT NULL | `popover`, `widget`, `external_survey`, `api`
`questions` | jsonb | NULL | Array of survey questions
`appearance` | jsonb | NULL | Styling configuration
`start_date` | timestamp with tz | NULL | When survey becomes active
`end_date` | timestamp with tz | NULL | When survey ends
`created_at` | timestamp with tz | NOT NULL | Creation timestamp

### Question Types

```json
[
  {
    "id": "uuid",
    "type": "open",
    "question": "How can we improve?",
    "optional": false,
    "buttonText": "Submit"
  },
  {
    "id": "uuid",
    "type": "rating",
    "question": "How would you rate us?",
    "display": "number",
    "scale": 10,
    "lowerBoundLabel": "Not likely",
    "upperBoundLabel": "Very likely"
  },
  {
    "id": "uuid",
    "type": "single_choice",
    "question": "Which feature do you use most?",
    "choices": ["Feature A", "Feature B", "Feature C"]
  }
]
```

### Important Notes

- The view only exposes the columns above. Other Django model fields (`description`, `conditions`, `archived`, the flag/insight FK columns, iteration and response-sampling fields, AI summaries, etc.) are **not** queryable here — selecting them fails with `Unable to resolve field: <col>`. Run `SELECT *` or `read-data-warehouse-schema` if unsure.
- Survey name must be unique per team
- The default manager excludes soft-deleted surveys
