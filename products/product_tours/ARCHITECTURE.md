# Product Tours Architecture

Product tours allow PostHog users to implement automated onboarding and product walkthroughs, similar to tools like Userpilot and Product Fruits.

## Overview

Users create tours via the toolbar by selecting elements on their page and defining step content. Tours are stored in PostHog and delivered to end-users via posthog-js, with visibility controlled by internal feature flags.

## Data Model

### ProductTour

| Field                     | Type            | Description                                   |
| ------------------------- | --------------- | --------------------------------------------- |
| `id`                      | UUID            | Primary key                                   |
| `team`                    | FK(Team)        | Owner team                                    |
| `name`                    | string          | Tour name (unique per team when not archived) |
| `description`             | string          | Optional description                          |
| `internal_targeting_flag` | FK(FeatureFlag) | Auto-created flag for targeting               |
| `content`                 | JSON            | Tour steps, appearance, conditions            |
| `start_date`              | datetime        | When tour becomes active                      |
| `end_date`                | datetime        | When tour stops                               |
| `created_at`              | datetime        | Creation timestamp                            |
| `created_by`              | FK(User)        | Creator                                       |
| `archived`                | bool            | Soft delete flag                              |

### Content Schema

```json
{
  "steps": [
    {
      "selector": "string",
      "title": "string",
      "description": "string",
      "position": "top|bottom|left|right"
    }
  ],
  "appearance": {},
  "conditions": {
    "url": "string",
    "urlMatchType": "exact|contains|regex"
  }
}
```

## Internal Feature Flag

Each tour gets an auto-created feature flag that:

- Uses key format: `product-tour-targeting-{slugified_name}-{random_id}`
- Filters out users who have completed or dismissed the tour
- Activates when `start_date` is set
- Deactivates when `end_date` is reached or tour is archived

### Person Properties Tracked

- `$product_tour_completed/{tour_id}` - User finished the tour
- `$product_tour_dismissed/{tour_id}` - User dismissed the tour

## Event Tracking

Events sent by posthog-js:

| Event                    | Description             |
| ------------------------ | ----------------------- |
| `product tour shown`     | Tour displayed to user  |
| `product tour dismissed` | User dismissed tour     |
| `product tour completed` | User finished all steps |
| `product tour step seen` | Individual step viewed  |

## API Endpoints

| Method | Path                                     | Description  |
| ------ | ---------------------------------------- | ------------ |
| GET    | `/api/projects/{id}/product_tours/`      | List tours   |
| POST   | `/api/projects/{id}/product_tours/`      | Create tour  |
| GET    | `/api/projects/{id}/product_tours/{id}/` | Get tour     |
| PATCH  | `/api/projects/{id}/product_tours/{id}/` | Update tour  |
| DELETE | `/api/projects/{id}/product_tours/{id}/` | Archive tour |

## Future Enhancements (v2)

- User-provided targeting flag (`linked_flag`)
- Response sampling
- Recurring/iteration tours
- AI-powered tour generation
- Caching layer for SDK delivery
