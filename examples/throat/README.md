# Throat singing (kargyraa) demo

An old singer with a walrus moustache and a mullet throat-sings an original Finnish song
(`ukko-ja-takatukka.json`: words and tune written for this demo).

The melody's `"voice"` block turns on the kargyraa style:

- `source.falseFolds` (0..1): the false folds damp every other glottal pulse, so a subharmonic an
  octave below the sung note carries the pitch. Unlike `roughness` it adds no jitter, so the
  harmonics stay sharp for the vowel sweeps (`Oo, uu, oo, aa, oo`) to pick out overtones.
- `artic.ventricular`: the false folds narrow the laryngeal vestibule, held between gestures.

## Render and watch

```bat
cargo run --release -p chimera-cli -- render notes examples\throat\ukko-ja-takatukka.json public\shows\ukko\ukko.wav male --tele public\shows\ukko\ukko.tele
```

Convert `ukko.wav` to `ukko.mp3` (or point `audio` at the wav), copy `show.json` into
`public\shows\ukko\`, then open `http://127.0.0.1:5317/?show=ukko` with `bun run dev`.
`"hair": true` on the voice draws the moustache and mullet; the mullet sways, and buzzes with the
voice's level.
