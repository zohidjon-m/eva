import type { HTMLAttributes } from "react";
import styles from "./Card.module.css";

/** A raised surface container — the building block for grouped content. */
export function Card({
  className,
  ...rest
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={[styles.card, className].filter(Boolean).join(" ")} {...rest} />
  );
}
