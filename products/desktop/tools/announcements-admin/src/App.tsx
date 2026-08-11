import { useEffect, useState } from "react";
import { capture, captureException, identify } from "./analytics";
import { type FlagRecord, fetchCurrentUser, fetchFlag } from "./api";
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
      // restoreSession is inside the try too: a token-refresh network failure
      // would otherwise strand the app on the boot loading screen.
      try {
        await handleCallback();
        const token = await restoreSession();
        setState(token ? { phase: "loading", token } : { phase: "signed-out" });
      } catch (error) {
        captureException(error);
        setState({ phase: "signed-out", error: String(error) });
      }
    })();
  }, []);

  useEffect(() => {
    if (state.phase !== "loading") return;
    const token = state.token;
    void (async () => {
      let flag: FlagRecord;
      try {
        flag = await fetchFlag(token);
      } catch (error) {
        captureException(error);
        setState({ phase: "error", message: String(error) });
        return;
      }
      setState({ phase: "ready", token, flag });
      // Identify is best-effort; the editor works without it.
      try {
        const user = await fetchCurrentUser(token);
        if (user.distinctId) identify(user.distinctId, user.label);
      } catch (error) {
        captureException(error);
      }
    })();
  }, [state]);

  const handleLogout = () => {
    capture("announcement admin logged out");
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
            onClick={() => {
              capture("announcement admin login started");
              void beginLogin();
            }}
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
