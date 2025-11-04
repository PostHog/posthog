# Live Debugger

Live Debugger provides runtime inspection capabilities for PostHog users by enabling breakpoints in production code. When a breakpoint is hit, the system captures local variables, stack traces, and execution context without interrupting the running application.

## Related Projects

- [https://github.com/PostHog/hogtrace](hogtrace), a DTrace-inspired language for defining
  instrumentation scripts. It includes a Rust-based VM that can evaluate expressions within
  the context of the client application safely.
- [https://github.com/PostHog/libdebugger](libdebugger), a library for runtime instrumentation
  of Python code.

## Flow

```text
    PostHog UI                                       User Application
    ─────────────                                    ────────────────
         │                                                  │
         │ (1) Create breakpoint                            │
         ▼                                                  │
    ┌─────────┐                                             │
    │ Postgres│                                             │
    └─────────┘                                             │
         │                                                  │
         │ (2) Fetch active breakpoints                     │
         │     (Project API key)                            │
         └─────────────────────────────────────────────────►│
                                                            │
                                                            │ (3) Breakpoint hit
                                                            │     Capture state
                                                            │
                                                            │ (4) Send event
    ┌───────────┐                                           │     $data_breakpoint_hit
    │ ClickHouse│ ◄─────────────────────────────────────────┘
    └───────────┘
         │
         │ (5) Query hits (HogQL)
         ▼
    PostHog UI
```

## Architecture

The system consists of three components working together. The backend stores breakpoint definitions in PostgreSQL, associating each breakpoint with a team, repository, file, and line number. When instrumented code executes, it sends breakpoint hit events to PostHog that are stored in ClickHouse for efficient querying. The frontend provides a GitHub repository browser where users can navigate source files, set breakpoints, and inspect captured runtime state.

Applications poll the external API using a Project API key to fetch active breakpoints for their repository. When code execution reaches a breakpoint line, the instrumentation layer captures the current state and sends it as a PostHog event. The system supports conditional breakpoints through optional Python expressions that determine whether to capture state at a given location.

## API Endpoints

The product exposes two primary endpoints. The `/api/environments/:team_id/live_debugger_breakpoints/` endpoint handles breakpoint management operations through standard CRUD methods. The `/api/environments/:team_id/live_debugger_breakpoints/active/` endpoint allows external applications to fetch enabled breakpoints using Project API key authentication, returning breakpoint configurations that applications use to instrument their code at runtime.

The `/api/environments/:team_id/live_debugger_breakpoints/breakpoint_hits/` endpoint queries ClickHouse for captured runtime state, retrieving events from the last hour with support for filtering by specific breakpoint and pagination. Each hit contains the captured variables, stack trace, timestamp, and execution context.

## Data Model

Breakpoints are identified by the combination of team, repository, filename, and line number. Each breakpoint can be enabled or disabled and may include a condition expression. Breakpoint hits are stored as PostHog events with the event name `$data_breakpoint_hit` containing properties for the breakpoint ID, file path, line number, function name, local variables, and stack trace.

The system enforces team isolation at both the database and API levels. Breakpoint queries automatically filter by team ID, and attempts to access breakpoints from other teams return 404 responses to prevent information disclosure.

## Security Considerations

The external API uses Project API key authentication to allow runtime applications to fetch breakpoints without requiring user credentials. This enables server-side applications, background workers, and other headless processes to participate in debugging sessions. The API validates that breakpoint IDs belong to the requesting team before returning hit data, preventing cross-team data access through breakpoint ID enumeration.
