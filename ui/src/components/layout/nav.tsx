import type { ComponentType, SVGProps } from "react";
import {
  ChatIcon,
  JournalIcon,
  LibraryIcon,
  InsightsIcon,
  ProfileIcon,
  SettingsIcon,
} from "../icons";
import { ChatSection } from "../../sections/ChatSection";
import { JournalSection } from "../../sections/JournalSection";
import { LibrarySection } from "../../sections/LibrarySection";
import { InsightsSection } from "../../sections/InsightsSection";
import { ProfileSection } from "../../sections/ProfileSection";
import { SettingsSection } from "../../sections/SettingsSection";

/** The six top-level destinations. Navigation is local state (this union),
 *  not a router — Eva is a single-window desktop app with a fixed sidebar. */
export type View =
  | "chat"
  | "journal"
  | "library"
  | "insights"
  | "profile"
  | "settings";

export interface NavItem {
  id: View;
  label: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  Section: ComponentType;
}

/** Single source of truth for the nav: drives the sidebar, the top-bar title,
 *  and which section renders. Order here is the order shown in the sidebar. */
export const NAV: NavItem[] = [
  { id: "chat", label: "Chat", icon: ChatIcon, Section: ChatSection },
  { id: "journal", label: "Journal", icon: JournalIcon, Section: JournalSection },
  { id: "library", label: "Library", icon: LibraryIcon, Section: LibrarySection },
  { id: "insights", label: "Insights", icon: InsightsIcon, Section: InsightsSection },
  { id: "profile", label: "Profile", icon: ProfileIcon, Section: ProfileSection },
  { id: "settings", label: "Settings", icon: SettingsIcon, Section: SettingsSection },
];
