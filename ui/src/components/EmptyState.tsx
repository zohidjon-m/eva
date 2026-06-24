import type { ReactNode } from "react";
import styles from "./EmptyState.module.css";

interface EmptyStateProps {
  /** An inline SVG (or any node) shown above the title. */
  icon: ReactNode;
  title: string;
  description: string;
  /** Optional quiet line beneath the description (e.g. "Coming soon"). */
  hint?: string;
}

/**
 * The shared centerpiece for every section screen in Phase 3. Each section is a
 * deliberate, well-composed empty state rather than a blank panel — so the app
 * already feels like a finished product that simply has no data yet.
 */
export function EmptyState({ icon, title, description, hint }: EmptyStateProps) {
  return (
    <div className={styles.wrap}>
      <div className={styles.icon} aria-hidden="true">
        {icon}
      </div>
      <h2 className={styles.title}>{title}</h2>
      <p className={styles.description}>{description}</p>
      {hint && <p className={styles.hint}>{hint}</p>}
    </div>
  );
}
