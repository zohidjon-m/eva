import { EmptyState } from "../components/EmptyState";
import { ProfileIcon } from "../components/icons";

/** Profile — what Eva understands about you (the self-model). */
export function ProfileSection() {
  return (
    <EmptyState
      icon={<ProfileIcon />}
      title="Your profile"
      description="The evolving picture of who you are — the people, values, and goals that matter to you. Eva builds it from your words, and you stay in control of it."
      hint="Coming in a later phase"
    />
  );
}
