import { EmptyState } from "../components/EmptyState";
import { InsightsIcon } from "../components/icons";

/** Insights — patterns and mood over time (analytics on demand). */
export function InsightsSection() {
  return (
    <EmptyState
      icon={<InsightsIcon />}
      title="Insights"
      description="As you write, Eva quietly notices patterns — your moods, recurring themes, and the threads running through your days. You'll see them here."
      hint="Coming in a later phase"
    />
  );
}
