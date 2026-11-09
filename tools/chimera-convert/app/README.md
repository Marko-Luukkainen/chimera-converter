# The converter app's UI

React + Vite + TypeScript, in Chimera's look. The Python server (`python -m chimera_convert.server`)
serves the built `dist/` and the API on http://127.0.0.1:5320.

    bun install
    bun run build        # dist/ for the server
    bun run dev          # http://127.0.0.1:5321 with live reload (the server must run for /api)
    bun run test         # note-edit rules (src/edit.ts)

`src/edit.ts` holds the editing rules (every syllable starts one note, in order; melisma notes
follow) and is the part to move into Chimera's own UI later, with `Roll.tsx`.
