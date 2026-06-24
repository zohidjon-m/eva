# Bundled fonts

Self-hosted so Eva loads no fonts from a CDN at runtime — the app stays fully
offline. Referenced by the `@font-face` rules in
[`ui/src/styles/tokens.css`](../../src/styles/tokens.css).

| File | Typeface | Role | License |
|---|---|---|---|
| `Fraunces-Variable.woff2` | Fraunces (latin, weight axis) | display / headings (`--font-display`) | SIL Open Font License 1.1 |
| `Inter-Variable.woff2` | Inter (latin, weight axis) | UI / body (`--font-ui`) | SIL Open Font License 1.1 |

Both are the latin-subset variable builds from the `@fontsource-variable`
packages. To refresh them:

```sh
curl -sSL -o Inter-Variable.woff2 \
  https://cdn.jsdelivr.net/npm/@fontsource-variable/inter/files/inter-latin-wght-normal.woff2
curl -sSL -o Fraunces-Variable.woff2 \
  https://cdn.jsdelivr.net/npm/@fontsource-variable/fraunces/files/fraunces-latin-wght-normal.woff2
```
