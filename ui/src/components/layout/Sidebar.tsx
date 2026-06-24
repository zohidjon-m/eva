import { NAV, type View } from "./nav";
import styles from "./Sidebar.module.css";

interface SidebarProps {
  active: View;
  onSelect: (view: View) => void;
}

/** The fixed left rail: Eva's wordmark over the six nav items. The active item
 *  is highlighted; selecting one swaps the section in the main area. */
export function Sidebar({ active, onSelect }: SidebarProps) {
  return (
    <nav className={styles.sidebar} aria-label="Primary">
      <div className={styles.brand}>
        <span className={styles.wordmark}>Eva</span>
        <span className={styles.subtitle}>journaling companion</span>
      </div>

      <ul className={styles.list}>
        {NAV.map(({ id, label, icon: Icon }) => {
          const isActive = id === active;
          return (
            <li key={id}>
              <button
                type="button"
                className={`${styles.item} ${isActive ? styles.itemActive : ""}`}
                aria-current={isActive ? "page" : undefined}
                onClick={() => onSelect(id)}
              >
                <Icon className={styles.icon} aria-hidden="true" />
                <span>{label}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
