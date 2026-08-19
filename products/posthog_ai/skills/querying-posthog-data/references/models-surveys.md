# Surveys

## Survey (`system.surveys`)

Surveys collect feedback from users through questions and forms.

### Columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key (UUID)
`name` | varchar(400) | NOT NULL | Survey name (unique per team)
`description` | text | NOT NULL | Survey description
`type` | varchar(40) | NOT NULL | `popover`, `widget`, `external_survey`, `api`
`conditions` | jsonb | NULL | Display conditions
`questions` | jsonb | NULL | Array of survey questions
`appearance` | jsonb | NULL | Styling configuration
`created_at` | timestamp with tz | NOT NULL | Creation timestamp
`start_date` | timestamp with tz | NULL | When survey becomes active
`end_date` | timestamp with tz | NULL | When survey ends
`updated_at` | timestamp with tz | NOT NULL | Last update timestamp
`archived` | boolean | NOT NULL | Whether archived
`created_by_id` | integer | NULL | Creator user ID
`linked_flag_id` | integer | NULL | User-managed FK to feature flag
`targeting_flag_id` | integer | NULL | Auto-managed targeting flag
`internal_targeting_flag_id` | integer | NULL | Internal targeting flag
`internal_response_sampling_flag_id` | integer | NULL | Response sampling flag
`responses_limit` | integer | NULL | Max responses to collect
`linked_insight_id` | integer | NULL | FK to linked insight
`iteration_count` | integer | NULL | Number of iterations
`iteration_frequency_days` | integer | NULL | Days between iterations
`current_iteration` | integer | NULL | Current iteration number
`schedule` | varchar(40) | NULL | `once`, `recurring`, `always`
`enable_partial_responses` | boolean | NULL | Allow partial responses
`enable_iframe_embedding` | boolean | NOT NULL | Allow iframe embedding
`headline_summary` | text | NULL | AI-generated summary
`question_summaries` | jsonb | NULL | Per-question AI summaries
`response_sampling_*` | various | NULL | Response sampling configuration

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

### Key Relationships

- **Feature Flags**: Multiple flag relationships via `system.feature_flags`
- **Insight**: `linked_insight_id` -> `system.insights.id`

### Important Notes

- Survey name must be unique per team
- Internal flags (`targeting_flag`, `internal_targeting_flag`, `internal_response_sampling_flag`) are auto-managed
- `linked_flag` is user-managed and optional
