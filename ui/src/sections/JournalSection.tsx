import { EmptyState } from "../components/EmptyState";
import { JournalIcon } from "../components/icons";

/** Journal — browse the L0 vault (daily Markdown entries) by date. */
export function JournalSection() {
  return (
    <EmptyState
      icon={<JournalIcon />}
      title="Your journal"
      description="Every entry you write is saved here as a private, day-by-day record — plain text on your own machine that you can read back any time."
      hint="Browsing arrives in Phase 7"
    />
  );
}
