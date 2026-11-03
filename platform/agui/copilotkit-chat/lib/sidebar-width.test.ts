import assert from "node:assert/strict";
import { test } from "node:test";
import { DEFAULT, MAX, MIN, STEP, clampWidth, parseWidth, stepWidth } from "./sidebar-width.ts";

test("clampWidth keeps a value inside [MIN, MAX], clamps outside it", () => {
  assert.equal(clampWidth(MIN), MIN);
  assert.equal(clampWidth(MAX), MAX);
  assert.equal(clampWidth(320), 320);
  assert.equal(clampWidth(MIN - 50), MIN);
  assert.equal(clampWidth(MAX + 50), MAX);
});

test("parseWidth: a valid stored width, clamped; DEFAULT for null, junk or NaN", () => {
  assert.equal(parseWidth("320"), 320);
  assert.equal(parseWidth(String(MAX + 100)), MAX);
  assert.equal(parseWidth(String(MIN - 100)), MIN);
  assert.equal(parseWidth(null), DEFAULT);
  assert.equal(parseWidth(""), DEFAULT);
  assert.equal(parseWidth("not a number"), DEFAULT);
  assert.equal(parseWidth("NaN"), DEFAULT);
});

test("stepWidth moves by STEP and clamps at the bounds", () => {
  assert.equal(stepWidth(260, 1), 260 + STEP);
  assert.equal(stepWidth(260, -1), 260 - STEP);
  assert.equal(stepWidth(MAX, 1), MAX);
  assert.equal(stepWidth(MIN, -1), MIN);
});
