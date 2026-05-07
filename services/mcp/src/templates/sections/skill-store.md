### REQUIRED FIRST STEP — call `prime`

Before responding to the user's first PostHog request this session, run `posthog:exec({command: "prime"})`. The response carries the active environment, the tool index, and the team skill catalog the user expects you to know. Without it your answers will miss team standards. Treat the prime response as authoritative for the rest of the session.
