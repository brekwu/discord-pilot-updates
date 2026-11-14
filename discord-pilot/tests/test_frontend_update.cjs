"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

// Run the actual browser code with mocked HTTP requests. No browser download
// or external packages are necessary to regression-test the reconnect logic.
const source = fs.readFileSync(path.join(__dirname, "..", "web", "app.js"), "utf8")
  .replace(/\binit\(\);\s*$/, "");

async function simulateUpdate({portChanged}) {
  const redirects = [];
  let bootChecks = 0;
  let assetChecks = 0;
  let healthChecks = 0;
  const ctx = {
    document: {},
    localStorage: {getItem: () => ""},
    window: {
      location: {
        hostname: "127.0.0.1", port: "8765", pathname: "/", protocol: "http:",
        replace: url => redirects.push(url),
      },
    },
    AbortSignal,
    setTimeout: callback => {queueMicrotask(callback); return 1;},
    clearTimeout: () => {},
    fetch: async url => {
      const target = String(url);
      if (target.startsWith("/api/bootstrap")) {
        bootChecks++;
        if (portChanged) throw new TypeError("Failed to fetch");
        return {ok: true, json: async () => ({version: "0.4.6"})};
      }
      if (target.startsWith("/assets/app.js")) {
        assetChecks++;
        return {ok: true};
      }
      if (target.includes("/api/health")) {
        healthChecks++;
        if (target.startsWith("http://127.0.0.1:8766/")) {
          return {ok: true, json: async () => ({discord_pilot: true, version: "0.4.6"})};
        }
        throw new TypeError("Failed to fetch");
      }
      throw new Error(`Unexpected fetch ${target}`);
    },
  };
  vm.createContext(ctx);
  vm.runInContext(source, ctx, {filename: "web/app.js"});
  await vm.runInContext('waitForVersion("0.4.5", "0.4.6")', ctx);
  assert.equal(redirects.length, 1);
  if (portChanged) {
    assert.match(redirects[0], /^http:\/\/127\.0\.0\.1:8766\/\?updated=/);
    assert.ok(healthChecks >= 2, "alternative port must be confirmed twice");
  } else {
    assert.match(redirects[0], /^\/\?updated=/);
    assert.ok(bootChecks >= 2, "backend must be confirmed twice");
    assert.ok(assetChecks >= 2, "new JavaScript must be available");
  }
}

async function testVoiceWav() {
  const ctx = {document: {}, localStorage: {getItem: () => ""}, Blob};
  vm.createContext(ctx);
  vm.runInContext(source, ctx, {filename: "web/app.js"});
  // Voice recorder writes a standard signed PCM WAV that Vosk can read.
  const blob = vm.runInContext("voiceWav([new Float32Array(48000).fill(0.25)], 48000)", ctx);
  assert.equal(blob.type, "audio/wav");
  const bytes = await blob.arrayBuffer();
  const view = new DataView(bytes);
  const ascii = (offset, count) => Buffer.from(bytes, offset, count).toString("ascii");
  assert.equal(ascii(0, 4), "RIFF");
  assert.equal(ascii(8, 4), "WAVE");
  assert.equal(view.getUint16(22, true), 1, "must be mono");
  assert.equal(view.getUint32(24, true), 16000, "must be 16 kHz");
  assert.equal(view.getUint16(34, true), 16, "must be 16-bit PCM");
  assert.equal(blob.size, 44 + 16000 * 2, "48 kHz one-second input must resample to 16k");
  assert.ok(view.getInt16(44, true) > 8000, "resampled audio must contain microphone samples");
}

(async () => {
  await testVoiceWav();
  await simulateUpdate({portChanged: false});
  await simulateUpdate({portChanged: true});
  process.stdout.write("Frontend tests OK: microphone WAV, restart, asset availability, port recovery.\n");
})().catch(error => {console.error(error); process.exitCode = 1;});
