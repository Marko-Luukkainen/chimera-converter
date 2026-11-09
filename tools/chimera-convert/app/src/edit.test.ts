// node --experimental-strip-types --test src/edit.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { innerMelismas, mergePrev, moveEdge, moveNote, shiftSyllable, split, valid, type Note } from "./edit.ts";

const N = (start: number, end: number, midi: number, syl: number | null): Note => ({ start, end, midi, syl });
// "how I won" with "how" holding two pitches: how(F) ~(F) I(E) won(E)
const base = (): Note[] => [N(0, 0.6, 65, 0), N(0.6, 1.0, 65, null), N(1.0, 1.2, 64, 1), N(1.2, 1.8, 64, 2)];

test("valid melodies", () => {
  assert.ok(valid(base(), 3));
  assert.ok(!valid(base(), 4));
  assert.ok(!valid([N(0, 1, 60, null), N(1, 2, 60, 0)], 1));
});

test("the misplaced syllable fix: move I one note earlier, then fold the leftover", () => {
  const a = shiftSyllable(base(), 2, -1)!;
  assert.deepEqual(a.map((n) => n.syl), [0, 1, null, 2]);
  assert.ok(valid(a, 3));
  const b = mergePrev(a, 2)!;
  assert.deepEqual(b.map((n) => [n.start, n.end, n.syl]), [[0, 0.6, 0], [0.6, 1.2, 1], [1.2, 1.8, 2]]);
  assert.ok(valid(b, 3));
});

test("shifting needs a melisma note to move into", () => {
  assert.equal(shiftSyllable(base(), 3, -1), null); // the note before starts a syllable
  assert.equal(shiftSyllable(base(), 0, 1), null); // the first note must start one
  const later = shiftSyllable(base(), 0, -1);
  assert.equal(later, null);
});

test("split makes a melisma note, mergePrev undoes it", () => {
  const s = split(base(), 3, 1.5)!;
  assert.deepEqual(s.map((n) => n.syl), [0, null, 1, 2, null]);
  assert.deepEqual(mergePrev(s, 4), base());
  assert.equal(split(base(), 3, 1.21), null); // too short a half
  assert.equal(mergePrev(base(), 2), null); // a syllable's note can't be folded away
});

test("edges move a touching neighbour and stop at the others", () => {
  const a = moveEdge(base(), 2, "start", 0.8);
  assert.equal(a[1].end, 0.8);
  assert.equal(a[2].start, 0.8);
  const gap = [N(0, 0.5, 60, 0), N(1, 1.5, 62, 1)];
  assert.equal(moveEdge(gap, 1, "start", 0.2)[1].start, 0.5);
  assert.equal(moveEdge(gap, 0, "end", 0.7)[0].end, 0.7);
  assert.equal(moveEdge(gap, 0, "end", 0.01)[0].end, 0.05);
  assert.deepEqual(moveNote(gap, 1, -2)[1], N(0.5, 1, 62, 1));
});

test("melisma inside a word is flagged", () => {
  // words: "how" (1 syllable), "won-der" (2): a melisma on "won" is inside the word
  const ns = [N(0, 1, 65, 0), N(1, 1.5, 64, 1), N(1.5, 2, 63, null), N(2, 2.5, 62, 2)];
  const bad = innerMelismas(ns, [[0, 0], [1, 0], [1, 1]], [1, 2]);
  assert.deepEqual([...bad], [2]);
  assert.deepEqual([...innerMelismas(base(), [[0, 0], [1, 0], [2, 0]], [1, 1, 1])], []);
});
