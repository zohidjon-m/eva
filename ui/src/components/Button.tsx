import type { ButtonHTMLAttributes } from "react";
import styles from "./Button.module.css";

type Variant = "primary" | "ghost" | "subtle";
type Size = "sm" | "md";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

/** The one button in the app. Variants: primary (accent fill), ghost (bordered),
 *  subtle (quiet, text-only until hover). All colors come from tokens. */
export function Button({
  variant = "primary",
  size = "md",
  className,
  ...rest
}: ButtonProps) {
  const classes = [styles.button, styles[variant], styles[size], className]
    .filter(Boolean)
    .join(" ");
  return <button className={classes} {...rest} />;
}
