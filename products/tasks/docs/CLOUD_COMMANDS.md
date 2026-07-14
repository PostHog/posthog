# Cloud run commands

Cloud run clients send JSON-RPC commands through the task run `command` endpoint. User messages are delivered durably through the run's Temporal workflow before reaching the sandbox agent server.

The `user_message` command accepts `content`, `artifact_ids`, and an optional `steer` boolean. When `steer` is `true` and the active sandbox advertises native steering, the message is injected into the current turn at the next adapter boundary. The current turn remains responsible for completion, usage reporting, and the final turn-complete event.

If the sandbox does not advertise native steering, is not ready, is compacting, or has already completed the active turn, clients should retain queue behavior and deliver the message as a normal follow-up turn.
