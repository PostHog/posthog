# Autoresearch

## AutoresearchPipeline (`system.autoresearch_pipelines`)

A standing prediction question: a target event, a population, and a horizon ("who will download a file in the next 30 days?"). An agent searches for a model that answers it, and the product scores the population on a cadence, emitting one `autoresearch_prediction` event per person.

### Columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key
`team_id` | integer | NOT NULL | Team this pipeline belongs to
`name` | varchar(255) | NOT NULL | Human-readable name
`description` | text | NOT NULL | Free-text description (can be blank)
`target_event` | varchar(255) | NOT NULL | Event being predicted, for example `$pageview`
`horizon_days` | integer | NOT NULL | Predict whether the target occurs within N days
`status` | varchar(20) | NOT NULL | `draft`, `bootstrapping`, `running`, `converged`, `paused`, or `archived`
`iteration_budget` | integer | NOT NULL | Maximum training iterations allowed
`iteration_budget_remaining` | integer | NOT NULL | Iterations still available to spend
`output_person_property` | varchar(255) | NOT NULL | Person property the champion's score is written to
`last_scored_at` | timestamp with tz | NULL | When inference last ran
`created_at` | timestamp with tz | NOT NULL | Creation timestamp
`updated_at` | timestamp with tz | NOT NULL | Last modification timestamp

### Key Relationships

- Pipelines belong to a **Team** (`team_id`)
- A pipeline owns its training runs, iterations, trained models, operational runs, and suggestions. Those are not exposed as system tables; read them through the `autoresearch-*` API.

### Prediction events

Scoring emits `autoresearch_prediction` events. Each carries `$autoresearch_pipeline_id`, `$autoresearch_model_id`, `$autoresearch_p_y` (the predicted probability), `$autoresearch_prediction_date`, and `$autoresearch_person_id`, so predictions can be joined back to outcomes in `events`.
