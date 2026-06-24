import { useCallback, useEffect, useState } from "react";

/** The two themes Eva ships. There is no "system" runtime mode — we resolve the
 *  system preference to a concrete theme on first load, then the user owns it. */
export type Theme = "light" | "dark";

const STORAGE_KEY = "eva-theme";

/** The starting theme: a previously saved choice wins; otherwise mirror the OS. */
function initialTheme(): Theme {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved === "light" || saved === "dark") return saved;
  const prefersDark =
    window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
  return prefersDark ? "dark" : "light";
}

/**
 * Owns the active theme. Writes `data-theme` onto <html> (which flips the token
 * overrides in tokens.css) and persists the user's choice to localStorage so it
 * survives a reload. No dependencies — just React state + the DOM.
 */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(initialTheme);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(STORAGE_KEY, theme);
  }, [theme]);

  const toggle = useCallback(() => {
    setTheme((t) => (t === "dark" ? "light" : "dark"));
  }, []);

  return { theme, toggle };
}
