import { useEffect, useState } from "react";
import { type FlagRecord, fetchFlag } from "./api";
import { Editor } from "./Editor";
import { beginLogin, handleCallback, logout, restoreSession } from "./oauth";

type State =
  | { phase: "booting" }
  | { phase: "signed-out"; error?: string }
  | { phase: "loading"; token: string }
  | { phase: "ready"; token: string; flag: FlagRecord }
  | { phase: "error"; message: string };

export function App() {
  const [state, setState] = useState<State>({ phase: "booting" });

  useEffect(() => {
    void (async () => {
      try {
        await handleCallback();
      } catch (error) {
        setState({ phase: "signed-out", error: String(error) });
        return;
      }
      const token = await restoreSession();
      setState(token ? { phase: "loading", token } : { phase: "signed-out" });
    })();
  }, []);

  useEffect(() => {
    if (state.phase !== "loading") return;
    fetchFlag(state.token)
      .then((flag) => setState({ phase: "ready", token: state.token, flag }))
      .catch((error) => setState({ phase: "error", message: String(error) }));
  }, [state]);

  const handleLogout = () => {
    logout();
    setState({ phase: "signed-out" });
  };

  switch (state.phase) {
    case "booting":
    case "loading":
      return <p className="gate-note">Loading…</p>;
    case "signed-out":
      return (
        <div className="gate">
          <span className="eyebrow">PostHog Desktop · internal</span>
          <h1>Announcements</h1>
          <p>
            Compose and publish in-app announcements. Everything here edits one
            thing: the <code>posthog-desktop-announcements</code> flag payload.
          </p>
          {state.error && <p className="errors">{state.error}</p>}
          <button
            type="button"
            className="btn btn-publish"
            onClick={() => void beginLogin()}
          >
            Log in with PostHog
          </button>
        </div>
      );
    case "error":
      return (
        <div className="gate">
          <p className="errors">{state.message}</p>
          <button type="button" className="btn" onClick={handleLogout}>
            Start over
          </button>
        </div>
      );
    case "ready":
      return (
        <Editor
          token={state.token}
          flag={state.flag}
          onFlagUpdated={(flag) => setState({ ...state, flag })}
          onLogout={handleLogout}
        />
      );
  }
}
