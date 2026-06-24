import { EmptyState } from "../components/EmptyState";
import { ChatIcon } from "../components/icons";

/** Chat — the read loop (Phase 4 wires this to WS /chat). */
export function ChatSection() {
  return (
    <EmptyState
      icon={<ChatIcon />}
      title="Talk to Eva"
      description="This is where your conversation lives. Tell Eva about your day and she'll listen, remember, and reflect it back over time."
      hint="Chat arrives in Phase 6"
    />
  );
}
