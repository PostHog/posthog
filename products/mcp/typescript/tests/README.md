# API Integration Tests

These tests should verify that the API works as intended.

## Setup

1. **Configure environment:**

    ```bash
    cp .env.test.example .env.test
    ```

    Edit `.env.test` and set an api token and base url for your local PostHog instance

## Running Tests

```bash
# Run all tests
npm run test

# Run tests in watch mode
npm run test:watch
```
