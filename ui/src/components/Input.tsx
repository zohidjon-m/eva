import type { InputHTMLAttributes, TextareaHTMLAttributes } from "react";
import styles from "./Input.module.css";

/** Single-line text input, token-styled with a calm focus ring. */
export function Input({
  className,
  ...rest
}: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input className={[styles.field, className].filter(Boolean).join(" ")} {...rest} />
  );
}

/** Multi-line variant — same styling, for the chat composer and longer fields. */
export function Textarea({
  className,
  ...rest
}: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={[styles.field, styles.textarea, className].filter(Boolean).join(" ")}
      {...rest}
    />
  );
}
