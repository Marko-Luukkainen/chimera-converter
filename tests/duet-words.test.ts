/**
 * The words at a duet head's mouth for a Finnish melody, and the Nordic letters the Hershey font
 * lacks (drawn as a base letter and stroked marks).
 */
import { describe, expect, test } from "bun:test";
import { initEngine } from "./harness.ts";

await initEngine();
const { lyricsToSyllables, finnishLyricsToSyllables, DEMO_SONGS } = await import("../src/wasm/engine.ts");
const { sungWords } = await import("../src/show/words.ts");
const { hersheyBase } = await import("../src/ui/render/vector.ts");

describe("duet words", () => {
  // the Finnish demo song as a melody file, as the converter writes one ("lang": "fi")
  const song = DEMO_SONGS.find((s) => s.language === "fi")!;
  const melody = { bpm: song.bpm, lyrics: song.lyrics, notes: song.notes, lang: "fi" };

  test("a Finnish melody's syllables fill its notes", () => {
    const w = sungWords(melody, finnishLyricsToSyllables(melody.lyrics));
    expect(w.shown.length).toBe(song.notes.length);
    expect(w.shown.slice(0, 4)).toEqual(["Jaak-", "ko", "kul-", "ta"]);
    expect(w.shown.slice(8, 11)).toEqual(["he-", "rää", "jo"]);
  });

  test("the English rules garble Finnish words (what the duet used to show, when anything)", () => {
    // they read only ASCII letters: "herää" loses its ää, and "Jaakko" is one held syllable; a song
    // whose count then missed its notes showed no words at all
    const en = lyricsToSyllables(melody.lyrics).map((s) => s.text);
    expect(en).toContain("her");
    expect(en).not.toContain("rää");
    expect(en.slice(0, 3)).toEqual(["Jaakko", "~", "~"]);
  });
});

describe("Nordic letters", () => {
  test("letters the Hershey font lacks are drawn from their base letters", () => {
    expect(hersheyBase("KÄÄNTÖ")).toBe("KAANTO");
    expect(hersheyBase("Åbo pöytä")).toBe("Abo poyta");
    expect(hersheyBase("plain")).toBe("plain");
  });
});
