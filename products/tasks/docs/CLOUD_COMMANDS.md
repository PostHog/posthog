# Cloud run commands

Cloud run clients send JSON-RPC commands through the task run `command` endpoint. User messages are delivered durably through the run's Temporal workflow before reaching the sandbox agent server.

The `user_message` command accepts `content`, `artifact_ids`, and an optional `steer` boolean. When `steer` is `true` and the active sandbox advertises native steering, the message is injected into the current turn at the next adapter boundary. The current turn remains responsible for completion, usage reporting, and the final turn-complete event.

If the sandbox does not advertise native steering, is not ready, is compacting, or has already completed the active turn, clients should retain queue behavior and deliver the message as a normal follow-up turn.

## Rolling out native steering signals

Native steering signals require a receiver-first deployment because a Temporal capability query and the following signal can be handled by different worker versions.

1. Deploy the workflow handlers while leaving `TASKS_NATIVE_STEERING_SIGNALS_ENABLED` disabled.
2. Wait until every worker polling `TASKS_TASK_QUEUE` has the new signal handlers.
3. Enable `TASKS_NATIVE_STEERING_SIGNALS_ENABLED` for senders.

Production defaults the setting to disabled. Local development defaults it to enabled. While disabled, steer requests use the durable legacy follow-up signal and retain queue behavior.
