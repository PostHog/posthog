# Orchestra — demo

Demos the deploy → run → trigger → re-deploy flow with workflow code from [`replace-temporal`](https://github.com/PostHog/replace-temporal) (cloned next to this repo at `~/repos/replace-temporal`).

## One-time setup

```bash
./bin/start                                              # builds posthog/orchestra-runtime, boots dev
export POSTHOG_API_KEY=phx_...                           # PAT with orchestra:read + orchestra:write
export PATH="/Users/andyzhao/.orbstack/bin:$PATH"        # real docker, not the posthog wrapper
```

## Demo

1. Open `http://localhost:8010/orchestra` — empty state.
2. Deploy:

   ```bash
   bin/deploy-orchestra ~/repos/replace-temporal/demo
   ```

3. Active deployment card populates; `greeting_execution` appears as a chip.
4. Click **Trigger execution** → pick `greeting_execution` → input `{"name":"Andy","age":30}` → Trigger.
5. Click the new row in Executions — trace bars render (`build_greeting`, hatched `sleep 2s`, `log_greeting`).
6. Edit `~/repos/replace-temporal/demo/greeting.py`. Re-run `bin/deploy-orchestra`. Active card flips; old deployment goes `draining` → `stopped` once its queue empties.
7. Trigger again — runs on the new image.

## Cleanup

```bash
docker ps -aq --filter "label=posthog.product=orchestra" | xargs -r docker rm -f
```

## Notes

- `bin/deploy-orchestra <folder>` hashes the folder, AST-parses `@execution` names, builds `orchestra-user:team-<id>-<sha>`, POSTs metadata to PostHog. PostHog does the `docker run`.
- The runtime image (`posthog/orchestra-runtime`) is rebuilt by `bin/build-orchestra-runtime` (run automatically by `./bin/start`). Force a rebuild with `ORCHESTRA_RUNTIME_REBUILD=1`.
- The drain monitor is process-local — restarting PostHog leaves any draining containers alive.
- No ECR push yet; images stay local.
