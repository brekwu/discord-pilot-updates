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

async function testVoiceRecorderPreservesAllChunks() {
  const ctx = {document: {}, localStorage: {getItem: () => ""}, Blob};
  vm.createContext(ctx);
  vm.runInContext(source, ctx, {filename: "web/app.js"});
  const blob = vm.runInContext("buildVoiceBlob([new Blob([new Uint8Array(2048).fill(1)]), new Blob([new Uint8Array(3072).fill(2)])], 'audio/webm')", ctx);
  assert.equal(blob.type, "audio/webm");
  assert.equal(blob.size, 5120, "all chunks, including final data, must be preserved");
  const bytes = new Uint8Array(await blob.arrayBuffer());
  assert.equal(bytes[0], 1);
  assert.equal(bytes[2047], 1);
  assert.equal(bytes[2048], 2);
  assert.equal(bytes[5119], 2);
}

async function testFullMicrophoneLifecycle() {
  const elements = {
    voiceButton: {disabled: false, textContent: "", classList: {add() {}, remove() {}}},
    voiceStatus: {hidden: true, textContent: ""},
    voicePreview: {hidden: true, src: ""},
    requestText: {value: "", maxLength: 8000, dispatchEvent() {}},
  };
  let sent = null;
  const stream = {getTracks: () => [{stop() {}}]};
  class Recorder {
    static isTypeSupported(type) {return type === "audio/webm;codecs=opus";}
    constructor(_stream, options) {this.mimeType = options.mimeType; this.state = "inactive"; this.listeners = {};}
    start() {this.state = "recording"; this.ondataavailable({data: new Blob([new Uint8Array(2200).fill(7)])});}
    addEventListener(name, fn) {this.listeners[name] = fn;}
    stop() {
      this.state = "inactive";
      // Final chunk is only emitted when stop() is called.
      this.ondataavailable({data: new Blob([new Uint8Array(2300).fill(9)])});
      this.listeners.stop();
    }
  }
  const ctx = {
    document: {getElementById: id => elements[id]},
    localStorage: {getItem: () => ""},
    window: {MediaRecorder: Recorder},
    navigator: {mediaDevices: {getUserMedia: async () => stream}},
    Blob, Event,
    URL: {createObjectURL: () => "blob:recorded", revokeObjectURL() {}},
    setTimeout, clearTimeout, setInterval, clearInterval,
    fetch: async (path, options) => {
      assert.equal(path, "/api/transcribe");
      sent = options;
      return {ok: true, json: async () => ({text: "je veux créer un salon puis un deuxième", seconds: 5, segments: 2})};
    },
  };
  vm.createContext(ctx);
  vm.runInContext(source, ctx, {filename: "web/app.js"});
  await vm.runInContext("beginVoiceRecording()", ctx);
  await vm.runInContext("finishVoiceRecording()", ctx);
  assert.equal(sent.body.size, 4500, "final recorded chunk must reach the server");
  assert.equal(sent.headers["Content-Type"], "audio/webm;codecs=opus");
  assert.equal(elements.requestText.value, "je veux créer un salon puis un deuxième");
  assert.equal(elements.voicePreview.hidden, false, "the user should be able to replay audio");
}

(async () => {
  await testVoiceRecorderPreservesAllChunks();
  await testFullMicrophoneLifecycle();
  await simulateUpdate({portChanged: false});
  await simulateUpdate({portChanged: true});
  process.stdout.write("Frontend tests OK: background recorder chunks, playback, transcription, update recovery.\n");
})().catch(error => {console.error(error); process.exitCode = 1;});
