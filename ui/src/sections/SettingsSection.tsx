import { EmptyState } from "../components/EmptyState";
import { SettingsIcon } from "../components/icons";

/** Settings — the config store (vault path, model, voice, default persona). */
export function SettingsSection() {
  return (
    <EmptyState
      icon={<SettingsIcon />}
      title="Settings"
      description="Where you'll choose your vault location, manage the local model, set Eva's voice, and pick a default persona — all stored on your machine."
      hint="Coming in a later phase"
    />
  );
}
