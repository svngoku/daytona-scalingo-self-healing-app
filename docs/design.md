# Scalingo-inspired demo design

Reference: [Scalingo's French homepage](https://scalingo.com/fr/), reviewed on 17 November 2026. These are project design decisions drawn from the site, not an official Scalingo brand specification.

## Visual direction

The site pairs large regular-weight headings with generous spacing, warm dark navigation, orange primary actions, outlined secondary controls, and purple/orange campaign artwork. Its lower sections group product capabilities into modular cards. This dashboard adapts that hierarchy to incident investigation: a clear primary action, restrained panel borders, and readable evidence surfaces. Decorative artwork stays outside the log and diff panes.

## Typography

| Role | Font | Source |
| --- | --- | --- |
| Headings and product identity | ABC Favorit Regular, 400 | User-supplied WOFF2, bundled as `apps/dashboard/app/fonts/abc-favorit-regular.woff2` |
| Interface text and prose | IBM Plex Sans | Local regular font and bundled package weights |
| Commands, logs, identifiers, diffs | Geist Mono | Bundled package |

The supplied ABC font was identified by its internal metadata as ABC Favorit Regular, weight 400. Headings use that weight rather than a synthesized bold face. Font assets are served with the app.

## Shared color roles

The canonical CSS variables are in `apps/dashboard/app/globals.css`. Use the same roles in both themes. Dark is the default. The header's **Light theme** toggle uses UI SDK preferences to persist the selected theme in browser storage.

| Role | Dark | Light |
| --- | --- | --- |
| Page | `#15110e` | `#f7f2ec` |
| Navigation | `#1b140f` | `#fffaf5` |
| Surface / raised surface | `#221b16` / `#29211b` | `#fffdf9` / `#f4ede5` |
| Border | `#44372e` | `#d9cbbf` |
| Primary text | `#fff8f1` | `#26180f` |
| Links and accent text | `#ffad86` | `#9e350e` |
| Primary action / action text | `#ff601f` / `#1c0e00` | `#ff601f` / `#1c0e00` |
| Scalingo deployment | `#c0a9fa` | `#5f36a0` |
| Daytona sandbox | `#7bdded` | `#086579` |
| Success / failure | `#6ee7b7` / `#fda4af` | `#146244` / `#991e44` |

Orange identifies the main action; it does not replace status colors. Labels and icons carry the same meaning as their colors.

## Components and layout

Use [UI SDK React](https://ui-sdk.dev/docs/react) for interaction primitives and React Flow for the workflow graph. Keep controls compact, focus visible, and related actions near their evidence. The desktop layout separates the workflow, activity, execution evidence, and publication review; narrow screens stack these sections and allow code panes to scroll internally.

Show real provider and execution states. A local fixture is labeled as scripted, a validated patch is distinct from a published PR, and a PR is distinct from a tested Review App. The presentation should make the division of responsibility between Daytona, Scalingo, GitHub, and the orchestrator easy to follow.
