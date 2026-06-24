import { useState } from "react";
import { useBackendHealth } from "../../lib/useBackendHealth";
import { useTheme } from "../../lib/useTheme";
import { NAV, type View } from "./nav";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import styles from "./AppLayout.module.css";

/**
 * The application frame: a fixed sidebar, a top bar, and a scrollable main area
 * that renders the active section. Owns the only two pieces of app-wide state in
 * Phase 3 — the current view and the theme — and reads live backend health.
 */
export function AppLayout() {
  const [view, setView] = useState<View>("chat");
  const { theme, toggle } = useTheme();
  const { health, modelPresent } = useBackendHealth();

  const active = NAV.find((item) => item.id === view) ?? NAV[0];
  const { Section } = active;

  return (
    <div className={styles.shell}>
      <Sidebar active={view} onSelect={setView} />
      <TopBar
        title={active.label}
        health={health}
        modelPresent={modelPresent}
        theme={theme}
        onToggleTheme={toggle}
      />
      <main className={styles.main}>
        <Section />
      </main>
    </div>
  );
}
