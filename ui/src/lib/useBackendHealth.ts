import { useEffect, useState } from "react";

/**
 * Backend health as the UI understands it.
 * - "ok": backend answered 200 with status "ok"
 * - "down": backend unreachable or returned an error
 * - "checking": no answer yet (initial load)
 */
export type Health = "checking" | "ok" | "down";

/** Where the local FastAPI backend listens. Localhost only — Eva never reaches the network. */
const BACKEND_URL = "http://127.0.0.1:8420/health";

/** How often to re-poll the backend, in milliseconds. */
const POLL_MS = 3000;

/**
 * Polls the backend's /health endpoint on mount and every few seconds, so the UI
 * tracks the backend going up or down in near real time. This is the Phase-0
 * bridge-proof, lifted out of App.tsx into a hook so the top bar can surface it.
 */
export function useBackendHealth() {
  const [health, setHealth] = useState<Health>("checking");
  const [modelPresent, setModelPresent] = useState<boolean>(false);

  useEffect(() => {
    let cancelled = false;

    /** Hit /health once and fold the result into state. */
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

  return { health, modelPresent };
}
