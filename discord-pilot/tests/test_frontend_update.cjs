"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

// Run the actual browser code with mocked HTTP requests. No browser download
// or external packages are necessary to regression-test the reconnect logic.
const source = fs.readFileSync(path.join(__dirname, "..", "web", "app.js"), "utf8")
  .replace(/\binit\(\);\s*$/, "");
const html = fs.readFileSync(path.join(__dirname, "..", "web", "index.html"), "utf8");
assert.match(html, /id="requestText"[^>]*maxlength="50000"/, "long requests must fit in the real textarea");
assert.match(html, /id="requestLength"/, "show a visible character counter");
assert.doesNotMatch(source, /dépasse 8 000 caractères/, "old 8k validation must be removed");

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
    requestText: {value: "", maxLength: 50000, dispatchEvent() {}},
  };
  let sent = null;
  let decodedBytes = 0;
  const stream = {getTracks: () => [{stop() {}}]};
  class AudioContextMock {
    async decodeAudioData(bytes) {
      decodedBytes = bytes.byteLength;
      return {duration: 5};
    }
    async close() {}
  }
  class OfflineAudioContextMock {
    constructor(channels, length, rate) {
      assert.equal(channels, 1);
      assert.equal(rate, 16000);
      this.length = length;
      this.destination = {};
    }
    createBufferSource() {return {connect() {}, start() {}};}
    async startRendering() {return {getChannelData: () => new Float32Array(this.length).fill(0.2)};}
  }
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
    window: {MediaRecorder: Recorder, AudioContext: AudioContextMock, OfflineAudioContext: OfflineAudioContextMock},
    navigator: {mediaDevices: {getUserMedia: async () => stream}},
    Blob, Event, ArrayBuffer, DataView,
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
  assert.equal(decodedBytes, 4500, "browser decoding must receive all chunks including the final chunk");
  assert.equal(sent.body.size, 160044, "entire 5-second audio must be converted to PCM WAV");
  assert.equal(sent.headers["Content-Type"], "audio/wav");
  const wav = new DataView(await sent.body.arrayBuffer());
  assert.equal(wav.getUint32(24, true), 16000, "PCM WAV sample rate");
  assert.equal(wav.getUint32(40, true), 160000, "PCM WAV length");
  assert.equal(wav.getInt16(44, true), 6553, "sample conversion");
  assert.equal(elements.requestText.value, "je veux créer un salon puis un deuxième");
  assert.equal(elements.voicePreview.hidden, false, "the user should be able to replay audio");
  // Second independent dictation captures the exact editable modal field.
  const modalField = {
    tagName: "TEXTAREA", type: "textarea", id: "modal-details",
    value: "Début", maxLength: 50000, isConnected: true,
    getAttribute: () => null, closest: () => ({hidden: false}),
    dispatchEvent() {},
  };
  ctx.modalField = modalField;
  await vm.runInContext("toggleVoiceRecording(modalField)", ctx);
  await vm.runInContext("finishVoiceRecording()", ctx);
  assert.equal(modalField.value,
    "Début je veux créer un salon puis un deuxième",
    "Whisper must transcribe in the selected dynamic modal field, never only the main composer");
  assert.equal(elements.requestText.value, "je veux créer un salon puis un deuxième",
    "Dictation in another field may not overwrite the main command");
}

async function testEmptyModelPlanShowsEditableGuidance() {
  const elements = {
    requestText: {value: "Arrange le serveur à ta convenance"},
    generateButton: {textContent: ""},
    modeSelect: {value: "auto"},
    modelSelect: {value: ""},
  };
  const ctx = {
    document: {getElementById: id => elements[id]},
    localStorage: {getItem: () => ""},
    window: {},
    setTimeout: fn => {ctx.deferredRetry = fn; return 1;},
  };
  vm.createContext(ctx);
  vm.runInContext(source, ctx, {filename: "web/app.js"});
  vm.runInContext(`
    app.selected = "1567347687379050727";
    renderOverview = () => {};
    request = async () => ({needs_clarification: true, question: "Quel changement précis ?",
      examples: ["Crée un salon annonces", "Crée un rôle Membre"]});
    modal = config => {globalThis.lastModal = config;};
  `, ctx);
  await vm.runInContext("createPlan()", ctx);
  assert.equal(ctx.lastModal.title, "Préciser la demande");
  assert.equal(ctx.lastModal.fields.find(f => f.id === "instruction").value,
    "Arrange le serveur à ta convenance", "the user's original request must be preserved");
  assert.match(ctx.lastModal.fields[0].text, /Aucune modification effectuée/);
  await assert.rejects(ctx.lastModal.onConfirm({instruction: "Arrange le serveur à ta convenance"}),
    /Reformule la demande/);
  await ctx.lastModal.onConfirm({instruction: "Arrange le serveur à ta convenance", detail: "Crée un salon annonces"});
  assert.match(elements.requestText.value, /^Arrange le serveur à ta convenance\nPrécision : Crée un salon annonces$/);
  assert.equal(typeof ctx.deferredRetry, "function", "the edited request should be resubmitted after the modal closes");
}


function testUniversalVoiceFieldSafety() {
  const ctx = {
    document: {getElementById: () => null},
    localStorage: {getItem: () => ""},
    window: {}, Event,
  };
  vm.createContext(ctx);
  vm.runInContext(source, ctx, {filename: "web/app.js"});
  function field(type, value = "") {
    return {
      tagName: type === "textarea" ? "TEXTAREA" : "INPUT",
      type, value, id: "dynamic-question", readOnly: false,
      disabled: false, isConnected: true,
      getAttribute: () => null, closest: () => ({hidden: false}),
      dispatchEvent() {},
    };
  }
  ctx.question = field("textarea", "Question");
  ctx.implicitText = field("text");
  ctx.password = field("password");
  ctx.number = field("number");
  assert.equal(vm.runInContext("canDictateTo(question)", ctx), true);
  assert.equal(vm.runInContext("canDictateTo(implicitText)", ctx), true);
  assert.equal(vm.runInContext("canDictateTo(password)", ctx), false);
  assert.equal(vm.runInContext("canDictateTo(number)", ctx), false);
  assert.equal(vm.runInContext('appendVoiceTranscript(question, "pour notre équipe")', ctx), true);
  assert.equal(ctx.question.value, "Question pour notre équipe");
  ctx.question.getAttribute = () => "8";
  assert.equal(vm.runInContext('appendVoiceTranscript(question, "texte trop long")', ctx), false);
  assert.equal(ctx.question.value, "Question pour notre équipe");
  ctx.question.closest = () => ({hidden: true});
  assert.equal(vm.runInContext('appendVoiceTranscript(question, "invisible")', ctx), false);
  assert.equal(ctx.question.value, "Question pour notre équipe");
  assert.match(html, /id="universalVoiceButton"/);
  assert.match(html, /id="universalVoiceStatus"/);
}

function testUniversalVoiceDockVisibleBeforeFocus() {
  const requestField = {
    id: "requestText", tagName: "TEXTAREA", disabled: false,
    readOnly: false, isConnected: true, closest: () => null,
  };
  const otherField = {
    id: "pollQuestion", tagName: "INPUT", type: "text",
    disabled: false, readOnly: false, isConnected: true, closest: () => null,
  };
  const button = {
    hidden: true, disabled: false, textContent: "",
    setAttribute(name, value) {this[name] = value;},
  };
  const dock = {hidden: true};
  const fields = {requestText: requestField, universalVoiceButton: button, universalVoiceDock: dock};
  const document = {activeElement: null, getElementById: id => fields[id] || null};
  const ctx = {document, localStorage: {getItem: () => ""}, window: {}};
  vm.createContext(ctx);
  vm.runInContext(source, ctx, {filename: "web/app.js"});

  vm.runInContext("updateUniversalVoiceButton()", ctx);
  assert.equal(dock.hidden, false, "microphone must be visible before selecting a text field");
  assert.equal(vm.runInContext("currentVoiceField()", ctx), requestField);
  document.activeElement = requestField;
  vm.runInContext("updateUniversalVoiceButton()", ctx);
  assert.equal(dock.hidden, true, "main composer retains its built-in microphone");

  ctx.otherField = otherField;
  vm.runInContext("voice.field = otherField; updateUniversalVoiceButton()", ctx);
  assert.equal(dock.hidden, false, "another focused field must offer the voice dock");
  assert.equal(vm.runInContext("currentVoiceField()", ctx), otherField);

  otherField.disabled = true;
  document.activeElement = null;
  vm.runInContext("updateUniversalVoiceButton()", ctx);
  assert.equal(dock.hidden, false, "closed/disabled fields fall back to the composer");
  assert.equal(vm.runInContext("currentVoiceField()", ctx), requestField);
}

(async () => {
  testUniversalVoiceFieldSafety();
  testUniversalVoiceDockVisibleBeforeFocus();
  await testVoiceRecorderPreservesAllChunks();
  await testFullMicrophoneLifecycle();
  await testEmptyModelPlanShowsEditableGuidance();
  await simulateUpdate({portChanged: false});
  await simulateUpdate({portChanged: true});
  process.stdout.write("Frontend tests OK: universal mic, modal dictation, recorder, transcription, update recovery.\n");
})().catch(error => {console.error(error); process.exitCode = 1;});
