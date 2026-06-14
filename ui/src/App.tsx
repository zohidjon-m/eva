import { useEffect, useState } from "react";
import "./App.css";

/**
 * Backend health as the UI understands it.
 *
 * - "ok": backend answered 200 with status "ok"
 * - "down": backend unreachable or returned an error
 * - "checking": no answer yet (initial load)
 */
type Health = "checking" | "ok" | "down";

/** Where the local FastAPI backend listens. Localhost only — Eva never reaches the network. */
const BACKEND_URL = "http://127.0.0.1:8420/health";

/** How often to re-poll the backend, in milliseconds. */
const POLL_MS = 3000;

/**
 * Eva's Phase-0 landing view: a single status dot that reflects whether the
 * local backend is alive. It exists to prove the shell ↔ backend bridge works
 * before any real features are built. Polls /health on mount and every few
 * seconds so the dot tracks the backend going up or down in near real time.
 */
function App() {
  const [health, setHealth] = useState<Health>("checking");
  const [modelPresent, setModelPresent] = useState<boolean>(false);

  useEffect(() => {
    let cancelled = false;

    /** Hit /health once and fold the result into component state. */
    async function check() {
      try {
        const res = await fetch(BACKEND_URL);
        const data = await res.json();
        if (cancelled) return;
        setHealth(res.ok && data.status === "ok" ? "ok" : "down");
        setModelPresent(Boolean(data.model_present));
      } catch {
        if (!cancelled) setHealth("down");
      }
    }

    check();
    const timer = setInterval(check, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  const label =
    health === "ok"
      ? "Backend connected"
      : health === "down"
        ? "Backend unreachable"
        : "Connecting…";

  return (
    <main className="landing">
      <h1 className="wordmark">Eva</h1>
      <p className="tagline">Your private journaling companion</p>

      <div className="status" role="status" aria-live="polite">
        <span className={`dot dot--${health}`} aria-hidden="true" />
        <span className="status__label">{label}</span>
      </div>

      <p className="model-line">
        Model: {modelPresent ? "ready" : "not installed yet"}
      </p>
    </main>
  );
}

export default App;
