import { EmptyState } from "../components/EmptyState";
import { LibraryIcon } from "../components/icons";

/** Library — reference material Eva can draw on (corpus). */
export function LibrarySection() {
  return (
    <EmptyState
      icon={<LibraryIcon />}
      title="Your library"
      description="Add notes, articles, or books you want Eva to know about. She'll draw on this reference material when it's relevant to your conversations."
      hint="Coming in a later phase"
    />
  );
}
