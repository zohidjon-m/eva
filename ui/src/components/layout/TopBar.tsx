import { useState } from "react";
import type { Health } from "../../lib/useBackendHealth";
import type { Theme } from "../../lib/useTheme";
import { CheckIcon, MoonIcon, SunIcon } from "../icons";
import styles from "./TopBar.module.css";

interface TopBarProps {
  title: string;
  health: Health;
  modelPresent: boolean;
  theme: Theme;
  onToggleTheme: () => void;
}

/** Visual-only personas — the selector switches local state but does not yet
 *  call the backend (POST /persona arrives with the chat work). */
const PERSONAS = ["Close friend", "Coach", "Mentor"] as const;
type Persona = (typeof PERSONAS)[number];

/** The top bar: section title on the left; persona selector, the always-on
 *  "Offline" assurance, the live backend status dot, and the theme toggle on
 *  the right. */
export function TopBar({
  title,
  health,
  modelPresent,
  theme,
  onToggleTheme,
}: TopBarProps) {
  const [persona, setPersona] = useState<Persona>("Close friend");

  const healthLabel =
    health === "ok"
      ? modelPresent
        ? "Backend connected · model ready"
        : "Backend connected · model not installed"
      : health === "down"
        ? "Backend unreachable"
        : "Connecting…";

  return (
    <header className={styles.topbar}>
      <h1 className={styles.title}>{title}</h1>

      <div className={styles.right}>
        <div
          className={styles.personas}
          role="radiogroup"
          aria-label="Persona"
        >
          {PERSONAS.map((p) => (
            <button
              key={p}
              type="button"
              role="radio"
              aria-checked={p === persona}
              className={`${styles.persona} ${p === persona ? styles.personaActive : ""}`}
              onClick={() => setPersona(p)}
            >
              {p}
            </button>
          ))}
        </div>

        <span className={styles.offline} title="Eva runs entirely on your machine">
          <CheckIcon className={styles.offlineCheck} aria-hidden="true" />
          Offline
        </span>

        <span
          className={styles.health}
          role="status"
          aria-live="polite"
          title={healthLabel}
        >
          <span
            className={`${styles.dot} ${styles[`dot_${health}`]}`}
            aria-hidden="true"
          />
          <span className={styles.healthLabel}>{healthLabel}</span>
        </span>

        <button
          type="button"
          className={styles.themeToggle}
          onClick={onToggleTheme}
          aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        >
          {theme === "dark" ? <SunIcon /> : <MoonIcon />}
        </button>
      </div>
    </header>
  );
}
