"use strict";

const $ = (id) => document.getElementById(id);
const app = { csrf: "", bootstrap: null, selected: localStorage.getItem("pilotGuild") || "", details: null, history: [], plan: null, tab: "studio", models: [], catalog: {features: [], providers: {}}, moduleData: null, interactiveData: null, busy: false, updateAvailable: false };
// No personal server identifiers are shipped in public updates; Discord provides real names after login.
const known = {};
const actionNames = { create_category: "Créer une catégorie", create_text_channel: "Créer un salon textuel", create_voice_channel: "Créer un salon vocal", create_role: "Créer un rôle", rename_channel: "Renommer un salon", rename_role: "Renommer un rôle", set_topic: "Modifier la description", send_message: "Publier un message", make_private: "Rendre un salon privé", lock_channel_writing: "Lecture seule pour les membres", delete_channel: "SUPPRIMER UN SALON", delete_role: "SUPPRIMER UN RÔLE", configure_welcome: "Activer les bienvenues automatiques", configure_farewell: "Activer les au-revoir automatiques", configure_invites: "Activer le compteur d'invitations", suggest_integration: "Installer un bot externe (autorisation requise)", set_module: "Configurer un module local", configure_module: "Configurer le module natif", set_role_access: "Modifier les accès du rôle", publish_ticket_panel: "Publier le panneau interactif des tickets", publish_application_panel: "Publier le formulaire interactif des candidatures" };
const icons = ["⌂", "♧", "♜", "▤"];
let serverWasUnavailable = false;
const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));
const voice = { stream: null, recorder: null, chunks: [], timer: null, clock: null, startedAt: 0, previewUrl: null, busy: false, target: null, field: null };

function dom(tag, className, value) { const node = document.createElement(tag); if (className) node.className = className; if (value !== undefined) node.textContent = String(value); return node; }
function replace(node, children) { node.replaceChildren(...children); }
function abbreviate(s) { return (s || "S").split(/\s+/).filter(Boolean).slice(0, 2).map(x => x[0]).join("").toUpperCase(); }
function time(iso) { try { return new Date(iso).toLocaleString("fr-FR", {dateStyle: "medium", timeStyle: "short"}); } catch { return ""; } }
function updateRequestLength() {
  const count = $("requestText").value.length;
  const indicator = $("requestLength");
  if (indicator) indicator.textContent = `${count.toLocaleString("fr-FR")} / 50 000 caractères`;
}

async function request(path, options = {}) {
  const init = { ...options, headers: { ...(options.headers || {}), "X-Pilot-CSRF": app.csrf } };
  if (options.data !== undefined) { init.method = options.method || "POST"; init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(options.data); }
  let res;
  try { res = await fetch(path, init); }
  catch (error) {
    if (error instanceof TypeError) throw new Error("Connexion locale interrompue. Discord Pilot essaie de se reconnecter automatiquement.");
    throw error;
  }
  let data = {};
  try { data = await res.json(); } catch { throw new Error("Réponse serveur illisible."); }
  if (!res.ok) throw new Error(data.error || `Erreur ${res.status}`);
  return data;
}

async function waitForDiscordConnection(timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const status = await request("/api/bootstrap");
    if (status.online) return status;
    if (status.error) throw new Error(status.error);
    if (!status.connecting) throw new Error("Connexion arrêtée. Vérifie le token du bot Discord.");
    await new Promise(resolve => setTimeout(resolve, 700));
  }
  throw new Error("Discord ne répond pas encore. Vérifie ta connexion Internet et le statut du bot avant de réessayer.");
}

let toastTimer;
function toast(text, error = false) { const box = $("toast"); box.textContent = text; box.className = `toast${error ? " error" : ""}`; box.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => box.hidden = true, 5700); }

function voiceStatus(message) {
  const el = $("voiceStatus");
  el.hidden = false;
  el.textContent = message;
  const floatingStatus = $("universalVoiceStatus");
  if (floatingStatus) floatingStatus.textContent = message;
}

/** Dictée dans les entrées métier sans toucher aux mots de passe ni aux chiffres. */
function canDictateTo(field) {
  if (!field) return false;
  const editable = field.tagName === "TEXTAREA" ||
    (field.tagName === "INPUT" && ["text", "search", "email", "url", "tel"].includes(field.type));
  return editable && !field.disabled && !field.readOnly && field.id !== "requestText";
}

function activeVoiceTarget(field) {
  return field && field.isConnected !== false &&
    !(field.closest?.("#modalBackdrop")?.hidden);
}

function appendVoiceTranscript(field, transcript) {
  if (!field || field.disabled || field.readOnly || !activeVoiceTarget(field)) return false;
  const candidate = [String(field.value || "").trim(), String(transcript || "").trim()].filter(Boolean).join(" ");
  const limitAttr = typeof field.getAttribute === "function" ? field.getAttribute("maxlength") : null;
  const explicitLimit = limitAttr !== null && limitAttr !== undefined ? Number(limitAttr)
    : typeof field.maxLength === "number" && field.maxLength > 0 ? field.maxLength : -1;
  if (explicitLimit >= 0 && candidate.length > explicitLimit) return false;
  field.value = candidate;
  field.dispatchEvent(new Event("input", {bubbles: true}));
  return true;
}

function currentVoiceField() {
  // The persistent dock defaults to the main request composer. When another
  // editable field is selected (including a modal), keep the target there.
  const selected = voice.stream ? voice.target : voice.field;
  if (selected && activeVoiceTarget(selected) &&
      (selected.id === "requestText" || canDictateTo(selected))) return selected;
  return $("requestText");
}

function updateUniversalVoiceButton() {
  const button = $("universalVoiceButton");
  if (!button) return;
  const active = currentVoiceField();
  // The main composer already displays an inline microphone while focused.
  // Elsewhere, always show the dock without requiring a prior input focus.
  const mainComposerFocused = active?.id === "requestText" &&
    document.activeElement?.id === "requestText";
  button.hidden = !active || !activeVoiceTarget(active) ||
    (mainComposerFocused && !voice.stream);
  const dock = $("universalVoiceDock");
  if (dock) dock.hidden = button.hidden;
  button.disabled = Boolean(voice.busy);
  button.textContent = voice.stream ? "■ Arrêter la dictée" : "🎙 Dicter ici";
  button.setAttribute("aria-label", voice.stream ? "Arrêter la dictée vocale" :
    "Dicter dans le champ sélectionné");
}

function initializeUniversalVoice() {
  document.addEventListener("focusin", event => {
    const field = event.target;
    if (canDictateTo(field)) voice.field = field;
    else if (field?.id === "requestText") voice.field = null;
    if (!voice.stream) updateUniversalVoiceButton();
  }, true);
  const button = $("universalVoiceButton");
  if (!button) return;
  button.addEventListener("pointerdown", event => event.preventDefault());
  button.onclick = () => toggleVoiceRecording(currentVoiceField());
  updateUniversalVoiceButton();
}

function buildVoiceBlob(chunks, mimeType) {
  // MediaRecorder retains compressed microphone frames even when JS events
  // are throttled in a background Opera tab; we assemble *all* chunks on stop.
  const blob = new Blob(chunks.filter(chunk => chunk.size > 0), {type: mimeType});
  if (blob.size < 1000) throw new Error("Enregistrement vide ou coupé. Réessaie et vérifie le microphone choisi dans Opera.");
  return blob;
}

async function encodeVoiceWav(recording) {
  // Decode only once recording has stopped. Unlike a ScriptProcessor callback,
  // this works even when Opera throttles JavaScript in a background tab.
  // The Windows EXE always accepts PCM WAV; it needn't ship an Opus decoder.
  const AudioContextType = window.AudioContext || window.webkitAudioContext;
  const OfflineContextType = window.OfflineAudioContext || window.webkitOfflineAudioContext;
  if (!AudioContextType || !OfflineContextType) {
    throw new Error("Ton navigateur ne permet pas de décoder le vocal. Essaie Opera à jour.");
  }
  const context = new AudioContextType();
  try {
    const decoded = await context.decodeAudioData(await recording.arrayBuffer());
    if (!decoded.duration || decoded.duration < 0.1) {
      throw new Error("Enregistrement sans son : vérifie le microphone sélectionné dans Opera.");
    }
    if (decoded.duration > 305) {
      throw new Error("Vocal trop long : limite de cinq minutes.");
    }
    const targetRate = 16000;
    const sampleCount = Math.ceil(decoded.duration * targetRate);
    const offline = new OfflineContextType(1, sampleCount, targetRate);
    const source = offline.createBufferSource();
    source.buffer = decoded;
    source.connect(offline.destination);
    source.start(0);
    const rendered = await offline.startRendering();
    const samples = rendered.getChannelData(0);
    const bytes = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(bytes);
    function label(offset, value) {for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i));}
    label(0, "RIFF"); view.setUint32(4, bytes.byteLength - 8, true);
    label(8, "WAVE"); label(12, "fmt "); view.setUint32(16, 16, true);
    view.setUint16(20, 1, true); view.setUint16(22, 1, true);
    view.setUint32(24, targetRate, true); view.setUint32(28, targetRate * 2, true);
    view.setUint16(32, 2, true); view.setUint16(34, 16, true);
    label(36, "data"); view.setUint32(40, samples.length * 2, true);
    for (let i = 0; i < samples.length; i++) {
      const value = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(44 + i * 2, Math.round(value * (value < 0 ? 32768 : 32767)), true);
    }
    return {blob: new Blob([bytes], {type: "audio/wav"}), seconds: samples.length / targetRate};
  } finally {
    await context.close();
  }
}

async function beginVoiceRecording() {
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    throw new Error("Microphone non disponible dans ce navigateur. Vérifie les autorisations d'Opera.");
  }
  const stream = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true}});
  try {
    const formats = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
    const mimeType = formats.find(type => window.MediaRecorder.isTypeSupported?.(type));
    const recorder = new window.MediaRecorder(stream, mimeType ? {mimeType, audioBitsPerSecond: 96000} : {audioBitsPerSecond: 96000});
    voice.chunks = [];
    recorder.ondataavailable = event => {if (event.data?.size) voice.chunks.push(event.data);};
    recorder.start(1000); // The stop event flushes all remaining data, not just the first second.
    voice.stream = stream; voice.recorder = recorder; voice.startedAt = Date.now();
    updateUniversalVoiceButton();
    voice.timer = setTimeout(() => finishVoiceRecording(), 300000);
    voice.clock = setInterval(() => {
      const seconds = Math.floor((Date.now() - voice.startedAt) / 1000);
      voiceStatus(`● Micro actif · ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")} · 5 minutes maximum. Tu peux utiliser une autre fenêtre.`);
    }, 1000);
    $("voiceButton").classList.add("recording");
    $("voiceButton").textContent = "■ Arrêter";
    updateUniversalVoiceButton();
    voiceStatus("● Enregistrement démarré. Parle normalement, même dans une autre fenêtre. Clique sur Arrêter pour transcrire (5 minutes maximum).");
  } catch (error) {
    stream.getTracks().forEach(track => track.stop());
    throw error;
  }
}

async function finishVoiceRecording() {
  if (!voice.stream || voice.busy) return;
  voice.busy = true;
  const button = $("voiceButton"); button.disabled = true;
  clearTimeout(voice.timer); clearInterval(voice.clock);
  const recorder = voice.recorder;
  const stream = voice.stream;
  const elapsed = (Date.now() - voice.startedAt) / 1000;
  let audio = null;
  let captureError = null;
  try {
    if (recorder.state !== "inactive") {
      await Promise.race([
        new Promise((resolve, reject) => {
          recorder.addEventListener("stop", resolve, {once: true});
          recorder.addEventListener("error", () => reject(new Error("L'enregistreur a été interrompu.")), {once: true});
          recorder.stop();
        }),
        delay(15000).then(() => {throw new Error("Le navigateur n'a pas terminé l'enregistrement.");}),
      ]);
    }
    audio = buildVoiceBlob(voice.chunks, recorder.mimeType || "audio/webm");
  } catch (error) {
    captureError = error;
  } finally {
    stream.getTracks().forEach(track => track.stop());
    voice.stream = null; voice.recorder = null; voice.chunks = [];
    button.classList.remove("recording"); button.textContent = "🎙 Dicter";
  }
  try {
    if (captureError) throw captureError;
    if (voice.previewUrl) URL.revokeObjectURL(voice.previewUrl);
    voice.previewUrl = URL.createObjectURL(audio);
    const preview = $("voicePreview"); preview.src = voice.previewUrl; preview.hidden = false;
    voiceStatus(`Enregistrement reçu : ${elapsed.toFixed(0)} s. Préparation du son complet pour la transcription…`);
    const wav = await encodeVoiceWav(audio);
    if (elapsed > 10 && wav.seconds < elapsed * 0.65) {
      throw new Error(`Le navigateur n'a conservé que ${wav.seconds.toFixed(1)} s d'un vocal de ${elapsed.toFixed(0)} s. Réécoute-le ci-dessous et vérifie le microphone.`);
    }
    voiceStatus(`${wav.seconds.toFixed(1)} s de son complet reçu. Transcription Whisper Small en cours… Au premier usage, téléchargement automatique d'environ 500 Mo.`);
    const result = await request("/api/transcribe", {method: "POST", headers: {"Content-Type": "audio/wav"}, body: wav.blob});
    if (!result.text?.trim()) throw new Error("Aucune parole détectée. Essaie de parler plus près du micro.");
    const input = voice.target || $("requestText");
    if (!appendVoiceTranscript(input, result.text)) {
      // Do not lose a completed transcript if the input was removed or filled meanwhile.
      voiceStatus("Texte transcrit (champ fermé ou limite atteinte) : " + result.text.trim());
      toast("La dictée n'a pas été insérée. Le texte reste visible et copiable dans l'état vocal.", true);
      return;
    }
    if (elapsed > 10 && result.seconds < elapsed * 0.65) {
      voiceStatus(`⚠ Dictée partielle : le fichier ne contient que ${result.seconds} s sur ${elapsed.toFixed(0)} s enregistrées. Réécoute l'audio ci-dessous pour vérifier ton microphone.`);
    } else {
      voiceStatus(`✓ ${result.seconds} s d'audio analysées, ${result.segments} passage(s) reconnus. Tu peux réécouter le vocal puis préparer le plan.`);
    }
  } catch (error) {
    voiceStatus("Transcription interrompue : " + error.message);
    toast(error.message, true);
  } finally {
    voice.busy = false; button.disabled = false; voice.target = null;
    updateUniversalVoiceButton();
  }
}

async function toggleVoiceRecording(field = $("requestText")) {
  if (voice.busy) return;
  if (voice.stream) return finishVoiceRecording();
  if (!activeVoiceTarget(field) || field.disabled || field.readOnly) {
    return toast("Sélectionne un champ de texte avant la dictée.", true);
  }
  voice.target = field;
  const button = $("voiceButton"); button.disabled = true;
  try { await beginVoiceRecording(); }
  catch (error) {
    voice.target = null;
    voiceStatus("Impossible de démarrer le micro : " + error.message);
    toast(error.message, true);
  } finally { button.disabled = false; updateUniversalVoiceButton(); }
}

function modal({title, description, fields = [], confirmText = "Confirmer", onConfirm}) {
  $("modalTitle").textContent = title;
  $("modalDescription").textContent = description;
  const inputs = {};
  const nodes = [];
  fields.forEach(f => {
    if (f.type === "info") { nodes.push(dom("p", "modal-info", f.text)); return; }
    if (f.type === "checkbox") {
      const wrapper = dom("label", "checkbox-row"); const inp = dom("input"); inp.type = "checkbox"; inp.checked = f.checked !== false;
      inputs[f.id] = inp; wrapper.append(inp, dom("span", "", f.label)); nodes.push(wrapper); return;
    }
    const label = dom("label", "modal-label", f.label);
    const inp = dom(f.type === "select" ? "select" : f.type === "textarea" ? "textarea" : "input", "modal-input"); inp.id = `modal-${f.id}`;
    if (f.type === "select") {
      for (const option of f.options || []) { const child = dom("option", "", option.label); child.value = option.value; inp.append(child); }
    } else {
      if (f.type === "textarea") inp.rows = 4;
      else inp.type = f.type || "text";
      inp.placeholder = f.placeholder || ""; inp.autocomplete = f.autocomplete || "off";
    }
    inp.value = f.value || "";
    inputs[f.id] = inp; label.htmlFor = inp.id; nodes.push(label, inp);
  });
  replace($("modalBody"), nodes);
  $("modalConfirm").textContent = confirmText;
  $("modalBackdrop").hidden = false;
  $("modalConfirm").onclick = async () => {
    const values = Object.fromEntries(Object.entries(inputs).map(([key, inp]) => [key, inp.type === "checkbox" ? inp.checked : inp.value]));
    $("modalConfirm").disabled = true;
    try { await onConfirm(values); $("modalBackdrop").hidden = true; }
    catch (e) { toast(e.message || "Une erreur est survenue.", true); }
    finally { $("modalConfirm").disabled = false; }
  };
  setTimeout(() => { const first = Object.values(inputs)[0]; if (first && first.type !== "checkbox") first.focus(); }, 50);
}

function guilds() {
  if (!app.bootstrap) return [];
  const live = app.bootstrap.guilds;
  const ids = new Set(live.map(g => g.id));
  const pinned = Object.entries(app.bootstrap.pinned).filter(([id]) => !ids.has(id)).map(([id, alias]) => ({id, name: known[id] || alias, alias, offline: true}));
  return [...live, ...pinned];
}

function currentGuild() { return guilds().find(g => g.id === app.selected); }

function renderGuilds() {
  const q = $("guildSearch").value.trim().toLowerCase();
  const all = guilds().filter(g => `${g.name} ${g.alias || ""} ${g.id}`.toLowerCase().includes(q));
  if (!all.length) { replace($("guildList"), [dom("p", "sidebar-empty", "Aucun serveur visible. Connecte ton bot ou ajoute un identifiant avec +.")]); return; }
  replace($("guildList"), all.map(g => {
    const button = dom("button", `guild-item${g.id === app.selected ? " active" : ""}`);
    const icon = dom("span", "guild-icon"); if (g.icon) { const img = dom("img"); img.src = g.icon; img.alt = ""; icon.append(img); } else icon.textContent = abbreviate(g.name);
    const names = dom("span", "guild-text"); names.append(dom("strong", "", g.alias || g.name), dom("small", "", g.offline ? "Hors ligne · accès à vérifier" : `${g.channels} salons · ${g.roles} rôles`));
    button.append(icon, names, dom("span", g.offline ? "guild-offline" : "guild-online"));
    button.onclick = () => selectGuild(g.id);
    return button;
  }));
}

function renderOverview() {
  const g = currentGuild();
  $("serverTitle").textContent = g ? (g.alias || g.name) : "Choisis un serveur";
  $("breadcrumbGuild").textContent = g ? (g.alias || g.name) : "Vue d'ensemble";
  $("serverSubtitle").textContent = g ? `${g.offline ? "Non accessible par le bot actuellement · " : "Connecté à Discord · "}ID ${g.id}` : "Connecte ton bot ou ajoute un identifiant.";
  const logo = $("serverMark"); replace(logo, []);
  if (g && g.icon) { const img = dom("img"); img.src = g.icon; img.alt = ""; logo.append(img); } else logo.textContent = g ? abbreviate(g.name) : "✦";
  $("statChannels").textContent = app.details ? app.details.channels.filter(c => c.type !== "other").length : (g && !g.offline ? g.channels : "—");
  $("statRoles").textContent = app.details ? app.details.roles.length : (g && !g.offline ? g.roles : "—");
  $("statPlans").textContent = g ? app.history.length : "—";
  $("aliasButton").disabled = !g; $("refreshButton").disabled = !g;
  $("generateButton").disabled = !g || app.busy;
  $("exportHistory").disabled = !g;
}

async function selectGuild(id) {
  app.selected = id; app.details = null; app.history = []; app.plan = null; app.moduleData = null; app.interactiveData = null;
  localStorage.setItem("pilotGuild", id);
  $("planPanel").hidden = true;
  renderGuilds(); renderOverview();
  await Promise.all([loadDetails(), loadHistory()]);
  await Promise.all([loadModules(), loadInteractive()]);
}

async function loadDetails() {
  const id = app.selected;
  if (!id || !app.bootstrap?.online || !app.bootstrap.guilds.some(g => g.id === id)) { app.details = null; renderStructure(); renderOverview(); return; }
  try { const data = await request(`/api/guild/${id}`); if (app.selected === id) app.details = data; }
  catch (e) { if (app.selected === id) { app.details = null; toast(e.message, true); } }
  renderStructure(); renderOverview();
}

async function loadHistory() {
  const id = app.selected;
  if (!id) return;
  try { const data = await request(`/api/history/${id}`); if (app.selected === id) app.history = data.plans; }
  catch (e) { toast(e.message, true); }
  if (app.plan) { const fresh = app.history.find(p => p.id === app.plan.id); if (fresh) app.plan = fresh; }
  renderHistory(); renderOverview(); renderPlan();
}

function renderStructure() {
  const target = $("structureContent");
  if (!app.details) { replace(target, [dom("p", "empty", "Structure inaccessible : le bot doit être connecté et présent sur ce serveur.")]); return; }
  const {channels, categories, roles} = app.details;
  const salons = dom("div", "structure-box"); salons.append(dom("h4", "", `Salons (${channels.length})`));
  const sections = [...categories, {id: null, name: "SANS CATÉGORIE"}];
  for (const category of sections) {
    const subset = channels.filter(c => c.category_id === category.id && c.type !== "other" && c.id !== category.id);
    if (!subset.length) continue;
    const group = dom("div", "category-block"); group.append(dom("strong", "", category.name));
    subset.forEach(c => { const row = dom("div", "channel-row"); row.append(dom("span", "", c.type === "voice" ? "◖" : "#"), dom("span", "", c.name)); group.append(row); });
    salons.append(group);
  }
  const members = dom("div", "structure-box"); members.append(dom("h4", "", `Rôles (${roles.length})`));
  roles.forEach(r => members.append(dom("span", "role-item", `◈ ${r.name}`)));
  if (!roles.length) members.append(dom("p", "sidebar-empty", "Aucun rôle personnalisé."));
  replace(target, [salons, members]);
}

function renderHistory() {
  if (!app.selected || !app.history.length) { replace($("historyContent"), [dom("p", "empty", "Aucune demande enregistrée pour ce serveur.")]); return; }
  replace($("historyContent"), app.history.map(p => {
    const article = dom("article", "history-item"); const head = dom("div", "history-head");
    const name = dom("div"); name.append(dom("strong", "", p.prompt.length > 220 ? p.prompt.slice(0, 220) + "…" : p.prompt), dom("small", "", `${time(p.created_at)} · ${p.mode} · ${p.actions.length} action(s)`));
    const badge = dom("span", `pill ${p.status === "completed" ? "success" : ["failed", "partial"].includes(p.status) ? "failed" : ""}`, stateName(p.status));
    if (p.verification) name.append(dom("small", "", `Contrôle Discord : ${p.verification.verified} confirmé(s), ${p.verification.local_only} configuration(s) locale(s), ${p.verification.unverified} non vérifié(s), ${p.verification.mismatch} écart(s)`));
    head.append(name, badge); article.append(head);
    const details = dom("details"); details.append(dom("summary", "", "Afficher les actions et résultats"));
    const ol = dom("ol"); p.actions.forEach((a, index) => {
      const line = dom("li", "", actionDescription(a)); const result = (p.results || []).find(r => r.index === index);
      if (result) line.append(dom("small", "", `↳ ${stateName(result.status)} — ${result.detail}`)); ol.append(line);
    }); details.append(ol); article.append(details);
    if (p.status === "draft") { const b = dom("button", "outline-button", "Revoir le plan →"); b.style.marginTop = "12px"; b.onclick = () => { app.plan = p; switchTab("studio"); renderPlan(); $("planPanel").scrollIntoView({behavior: "smooth", block: "center"}); }; article.append(b); }
    return article;
  }));
}

function stateName(s) { return ({draft: "Brouillon", queued: "En attente", running: "En cours", completed: "Terminé", partial: "Partiellement terminé", failed: "Échec", done: "Réussi", skipped: "Déjà présent", blocked: "Non exécuté après échec", authorization_required: "Autorisation Discord requise"})[s] || s; }
function actionDescription(a) {
  if (a.type === "publish_ticket_panel" || a.type === "publish_application_panel") return `${actionNames[a.type]} · visible dans le salon configuré`;
  if (a.type === "set_module") return `${a.enabled === "true" ? "Activer" : "Désactiver"} le module ${a.module}`;
  if (a.type === "configure_module") {
    const settings = Object.entries(a).filter(([key]) => !["type", "module", "enabled"].includes(key)).map(([key, value]) => `${key} : ${String(value).slice(0, 80)}`).join(" · ");
    return `${a.enabled === "true" ? "Activer" : "Désactiver"} ${a.module}${settings ? ` · ${settings}` : ""}`;
  }
  if (a.type === "set_role_access") {
    const terms = {keep: "inchangé", allow: "autorisé", deny: "refusé", inherit: "hérité"};
    return `Permissions de #${a.channel} pour ${a.role} · visibilité : ${terms[a.view]} · écrire/rejoindre : ${terms[a.participate]}`;
  }
  if (a.type === "set_channel_role_access") {
    const channel = app.details?.channels.find(c => c.id === a.channel_id)?.name || a.channel_id;
    const role = app.details?.roles.find(r => r.id === a.role_id)?.name || (a.role_id === app.selected ? "@everyone" : a.role_id);
    const terms = {keep: "inchangé", allow: "autorisé", deny: "refusé", inherit: "hérité"};
    return `Permissions de #${channel} pour ${role} · visibilité : ${terms[a.view]} · écrire/rejoindre : ${terms[a.participate]}`;
  }
  let text = `${actionNames[a.type] || a.type} · ${a.type === "suggest_integration" ? app.catalog.providers[a.provider]?.name || a.provider : a.channel || a.name || ""}`;
  if (a.category) text += ` → ${a.category}`;
  if (a.new_name) text += ` → ${a.new_name}`;
  if (a.role) text += ` (rôle ${a.role})`;
  if (a.content) text += ` : « ${a.content.slice(0, 90)} »`;
  if (a.topic) text += ` : ${a.topic.slice(0, 90)}`;
  return text;
}

function renderPlan() {
  const p = app.plan; $("planPanel").hidden = !p;
  if (!p) return;
  $("understoodPanel").hidden = !p.interpretation;
  $("understoodText").textContent = p.interpretation || "";
  $("planTitle").textContent = `${p.actions.length} action${p.actions.length > 1 ? "s" : ""} à ${p.status === "draft" ? "valider" : "suivre"}`;
  const automation = p.actions.some(a => a.type.startsWith("configure_"));
  const external = p.actions.some(a => a.type === "suggest_integration");
  $("planMeta").textContent = `Serveur : ${currentGuild()?.name || p.guild_id} · ${p.mode}` + (automation ? " · ⚠ Messages automatiques uniquement quand le bot local reste lancé. L'intent Server Members et la permission Gérer le serveur sont nécessaires pour le suivi des invitations." : "") + (external ? " · ⚠ L'installation d'un bot tiers nécessite ton autorisation Discord sur le site officiel : elle n'est jamais automatique." : "");
  $("planBadge").textContent = stateName(p.status);
  if (p.verification) $("planMeta").textContent += ` · Vérification Discord : ${p.verification.verified} OK, ${p.verification.local_only} locaux, ${p.verification.unverified} non vérifiés, ${p.verification.mismatch} écarts`;

  $("planBadge").className = `pill ${p.status === "completed" ? "success" : ["failed", "partial"].includes(p.status) ? "failed" : ""}`;
  replace($("planActions"), p.actions.map((a, i) => {
    const li = dom("li"); const num = dom("span", "step-num", i + 1);
    const words = dom("div", "step-text"); words.append(dom("strong", "", actionDescription(a)));
    const result = (p.results || []).find(r => r.index === i);
    if (result) {
      words.append(dom("small", "", result.detail));
      const providerUrl = app.catalog.providers[a.provider]?.url;
      if (a.type === "suggest_integration" && result.status === "authorization_required" && result.authorization_url === providerUrl) {
        const link = dom("a", "outline-button catalog-open", "↗ Autoriser sur le site officiel");
        link.href = providerUrl; link.target = "_blank"; link.rel = "noopener noreferrer";
        words.append(link);
      }
    }
    const marker = dom("span", `step-state ${result?.status || ""}`, result ? stateName(result.status) : a.type.startsWith("delete_") ? "Attention" : "À faire");
    li.append(num, words, marker); return li;
  }));
  const onlyExternal = p.actions.every(a => a.type === "suggest_integration");
  $("executeButton").disabled = p.status !== "draft" || (!onlyExternal && (!app.bootstrap?.online || !app.bootstrap.guilds.some(g => g.id === p.guild_id)));
  $("executeButton").textContent = p.status === "draft" ? (onlyExternal ? "Préparer les liens officiels ↗" : "Appliquer sur Discord ↗") : stateName(p.status);
}

async function bootstrap(quiet = false) {
  try {
    const data = await request("/api/bootstrap"); app.csrf = data.csrf;
    if (serverWasUnavailable) toast("Discord Pilot est de nouveau disponible.");
    serverWasUnavailable = false;
    const wasOnline = app.bootstrap?.online; app.bootstrap = data;
    $("connectionBadge").className = `connection-badge ${data.online ? "online" : ""}`;
    $("connectionBadge").innerHTML = "<i></i>"; $("connectionBadge").append(document.createTextNode(data.online ? "Bot connecté" : data.connecting ? "Connexion…" : "Déconnecté"));
    $("profileText").textContent = data.online ? data.bot?.name : data.error || "Non connecté";
    if (data.automation_warning && !quiet) toast(data.automation_warning, true);
    $("inviteButton").disabled = !data.online;
    $("updateVersion").textContent = `v${data.version || "?"}`;
    $("updateButton").classList.toggle("available", Boolean(data.update_pending) || app.updateAvailable);
    if (data.error && !quiet) toast(data.error, true);
    if (!app.selected && guilds().length) app.selected = guilds()[0].id;
    renderGuilds(); renderOverview();
    if (wasOnline !== data.online || (!quiet && app.selected)) {
      await Promise.all([loadDetails(), loadHistory()]);
      if (app.tab === "modules") await Promise.all([loadModules(), loadInteractive()]);
    }
    return true;
  } catch (e) {
    $("connectionBadge").className = "connection-badge";
    $("connectionBadge").textContent = "↻ Reconnexion…";
    $("profileText").textContent = "Redémarrage du serveur local…";
    if (!serverWasUnavailable || !quiet) toast("Reconnexion automatique en cours. Garde cette page ouverte.", true);
    serverWasUnavailable = true;
    return false;
  }
}

async function models() {
  try {
    const data = await request("/api/models"); app.models = data.models;
    $("ollamaStatus").textContent = data.available
      ? `✦ IA locale détectée · ${data.models.length} modèle(s) · la précision dépend du modèle choisi`
      : "⚠ Aucun modèle IA local détecté : commandes simples et listes structurées uniquement. Les demandes complexes nécessitent Ollama et un modèle de conversation.";
    replace($("modelSelect"), data.models.map(name => { const opt = dom("option", "", name); opt.value = name; return opt; }));
    $("modelSelect").hidden = !data.available || $("modeSelect").value === "local";
  } catch { $("ollamaStatus").textContent = "Mode sans IA disponible"; }
}

function switchTab(key) {
  app.tab = key;
  document.querySelectorAll(".tab").forEach(b => b.classList.toggle("active", b.dataset.tab === key));
  ["studio", "modules", "catalog", "structure", "history"].forEach(k => $(`${k}Tab`).hidden = k !== key);
  if (key === "modules" && app.selected && !app.moduleData) Promise.all([loadModules(), loadInteractive()]);
}

async function loadModules() {
  const id = app.selected;
  if (!id) { app.moduleData = null; renderModules(); return; }
  try {
    const data = await request(`/api/modules/${id}`);
    if (app.selected === id) app.moduleData = data;
  } catch (e) { if (app.selected === id) app.moduleData = null; toast(e.message, true); }
  renderModules();
}

function renderModules() {
  const data = app.moduleData;
  const grid = $("moduleGrid");
  if (!data) {
    $("moduleStatus").textContent = "Sélectionne un serveur pour charger les modules.";
    replace(grid, []); ["moduleLeaderboard", "inviteLeaderboard", "activityLeaderboard", "warningHistory"].forEach(id => replace($(id), []));
    $("issueWarning").disabled = true; return;
  }
  const enabled = Object.values(data.settings).filter(row => row.enabled).length;
  const unavailable = [];
  if (!data.members_intent) unavailable.push("Server Members Intent (rôle automatique, accueil/invitations, récompenses d'invitations)");
  if (!data.content_intent) unavailable.push("Message Content Intent (anti-liens, mots filtrés, Modmail)");
  $("moduleStatus").textContent = `${enabled} module(s) configuré(s) sur ce serveur. ${data.online ? "Bot connecté." : "Bot déconnecté : configuration impossible pour l'instant."} ${unavailable.length ? "Intents non disponibles : " + unavailable.join(" ; ") + ". Active-les dans Discord Developer Portal > Bot si besoin." : "Les intents requis sont connectés."} Les permissions Discord sont vérifiées lors des événements réels.`;
  replace(grid, data.modules.map(spec => {
    const current = data.settings[spec.id] || {};
    const article = dom("article", "module-card");
    const title = dom("div", "module-heading");
    title.append(dom("span", "module-symbol", spec.icon), dom("strong", "", spec.title));
    title.append(dom("span", `module-badge${current.enabled ? " on" : ""}`, current.enabled ? "CONFIGURÉ" : "INACTIF"));
    article.append(title, dom("p", "module-description", spec.description));
    const inputs = {};
    for (const [name, kind, labelText] of spec.fields) {
      const label = dom("label", "module-label", labelText);
      let input;
      if (["role", "optional_role", "text", "private_text", "optional_text", "voice", "category"].includes(kind)) {
        input = dom("select", "module-input");
        const empty = dom("option", "", kind.startsWith("optional") ? "Aucun (facultatif)" : "Choisir…"); empty.value = "";
        input.append(empty);
        const rows = kind === "category" ? (app.details?.categories || []) :
          kind.includes("role") ? (app.details?.roles || []) :
          (app.details?.channels || []).filter(c => c.type === (kind === "voice" ? "voice" : "text"));
        for (const item of rows) { const option = dom("option", "", item.name); option.value = item.id; input.append(option); }
      } else {
        input = dom("input", "module-input");
        input.type = kind === "positive_int" ? "number" : "text";
        if (kind === "positive_int") { input.min = "1"; input.max = "1000"; input.step = "1"; }
        input.placeholder = ({words: "mot, expression, autre mot", hour: "08:30", snowflake: "123456789012345678", emoji: "✅", message: "Ton annonce…", positive_int: "10", games: "rocket-league, valorant, fortnite, clash-of-clans"})[kind] || "";
        input.maxLength = kind === "message" ? 1800 : kind === "words" ? 1400 : 100;
      }
      input.value = current[name] || ""; inputs[name] = input;
      label.append(input); article.append(label);
    }
    const footer = dom("div", "module-actions");
    const toggle = dom("label", "module-toggle"); const checkbox = dom("input");
    checkbox.type = "checkbox"; checkbox.checked = Boolean(current.enabled);
    toggle.append(checkbox, dom("span", "", "Activer"));
    const save = dom("button", "primary-button", "Enregistrer"); save.disabled = !data.online;
    save.onclick = async () => {
      save.disabled = true;
      try {
        const payload = {enabled: checkbox.checked};
        Object.entries(inputs).forEach(([key, input]) => payload[key] = input.value.trim());
        const result = await request(`/api/modules/${data.guild_id}/${spec.id}`, {data: payload});
        toast(result.warning || `${spec.title} : configuration enregistrée.`);
        await loadModules(); await bootstrap(true);
      } catch (e) { toast(e.message, true); save.disabled = false; }
    };
    footer.append(toggle, save); article.append(footer);
    if (spec.id === "tickets") {
      const panel = dom("button", "outline-button", "🎟️ Publier le panneau de tickets");
      panel.disabled = !data.online || !current.enabled;
      panel.onclick = publishTicketPanel;
      article.append(panel);

      const diagnostic = dom("button", "outline-button", "🔍 Vérifier les tickets sur Discord");
      const output = dom("div", "module-description");
      diagnostic.onclick = async () => {
        if (!app.selected) return;
        diagnostic.disabled = true;
        replace(output, [dom("p", "", "Lecture du serveur Discord en cours…")]);
        try {
          const report = await request(`/api/interactive/${app.selected}/tickets/diagnostic`);
          const header = report.status === "ready_for_manual_test"
            ? "✓ Préparation vérifiée sur Discord. Teste encore une ouverture et une fermeture réelles."
            : "⚠ Certains contrôles échouent. Aucun changement effectué.";
          replace(output, [
            dom("strong", "", header),
            ...report.checks.map(c => dom("p", "", `${c.ok ? "✓" : "✗"} ${c.detail}`)),
            dom("p", "", "Ce contrôle est uniquement en lecture : il ne simule pas le clic d'un candidat."),
          ]);
        } catch (e) {
          replace(output, [dom("p", "", `Diagnostic indisponible : ${e.message}`)]);
        } finally { diagnostic.disabled = false; }
      };
      article.append(diagnostic, output);
      const smoke = dom("button", "outline-button", "🧪 Tester un ticket privé temporaire");
      const smokeOutput = dom("div", "module-description");
      smoke.onclick = () => {
        if (!app.selected) return toast("Sélectionne le serveur Discord.", true);
        const guildId = app.selected;
        modal({
          title: "Test réel technique des tickets",
          description: "Avec le bot connecté, créer un salon PRIVÉ temporaire dans la catégorie des tickets, vérifier les accès du staff, envoyer et relire un message, simuler l'archivage puis supprimer uniquement ce salon. Aucun ticket existant ne sera modifié. Un clic réel de candidat restera à tester.",
          confirmText: "Créer et supprimer le ticket de test",
          onConfirm: async () => {
            smoke.disabled = true;
            replace(smokeOutput, [dom("p", "", "Test Discord en cours…")]);
            try {
              const report = await request(`/api/interactive/${guildId}/tickets/smoke`,
                                           {data: {}});
              replace(smokeOutput, [
                dom("strong", "", report.status === "verified_technical_only"
                  ? "✓ Infrastructure testée sur Discord (clic candidat non testé)"
                  : "✗ Test technique incomplet"),
                dom("p", "", report.detail),
                ...(report.checks || []).map(x =>
                  dom("p", "", `${x.ok ? "✓" : "✗"} ${x.name} : ${x.detail}`)),
              ]);
            } catch (e) {
              replace(smokeOutput, [dom("p", "", `Test impossible : ${e.message}`)]);
            } finally {
              smoke.disabled = false;
            }
          }
        });
      };
      article.append(smoke, smokeOutput);
    }
    if (spec.id === "applications") {
      const panel = dom("button", "outline-button", "📝 Publier le formulaire de candidature");
      panel.disabled = !data.online || !current.enabled;
      panel.onclick = publishApplicationPanel;
      article.append(panel);
    }
    return article;
  }));
  const ranking = data.leaderboard || [];
  replace($("moduleLeaderboard"), ranking.length ? ranking.map((row, index) => {
    const r = dom("div", "module-rank");
    r.append(dom("span", "", `#${index + 1}`), dom("strong", "", `Membre ${row.member_id}`),
             dom("span", "", `Niveau ${row.level} · ${row.xp} XP`)); return r;
  }) : [dom("p", "empty", "Aucun XP enregistré : active le module et attends des messages réels.")]);
  const renderRanking = (element, rows, key, unit, empty) => replace($(element), rows.length ? rows.map((row, index) => {
    const r = dom("div", "module-rank");
    r.append(dom("span", "", `#${index + 1}`), dom("strong", "", `Membre ${row.member_id}`),
             dom("span", "", `${row[key]} ${unit}`)); return r;
  }) : [dom("p", "empty", empty)]);
  renderRanking("inviteLeaderboard", data.invite_leaderboard || [], "invites", "invitation(s) identifiée(s)", "Aucune invitation attribuable enregistrée.");
  renderRanking("activityLeaderboard", data.activity_leaderboard || [], "messages", "message(s)", "Aucun message comptabilisé.");
  replace($("warningHistory"), (data.warnings || []).length ? data.warnings.map(row => {
    const r = dom("div", "module-rank");
    r.append(dom("span", "", `#${row.count}`), dom("strong", "", `Membre ${row.member_id}`),
             dom("span", "", `${row.reason} · ${new Date(row.at).toLocaleString("fr-FR")}`)); return r;
  }) : [dom("p", "empty", "Aucun avertissement enregistré.")]);
  const warn = $("issueWarning");
  warn.disabled = !data.online || !data.settings.warnings?.enabled;
  warn.onclick = () => {
    const guildId = data.guild_id;
    modal({title: "Enregistrer un avertissement", description: "Le membre doit être présent sur ce serveur. Le motif sera publié dans le salon privé configuré. Aucune sanction n'est appliquée.",
      fields: [{id: "member_id", label: "ID du membre", placeholder: "123456789012345678"},
               {id: "reason", label: "Motif (2 à 300 caractères)", placeholder: "Expliquer la règle concernée"},
               {id: "confirmed", type: "checkbox", label: "Je confirme l'enregistrement de cet avertissement", checked: false}],
      confirmText: "Enregistrer", onConfirm: async values => {
        if (!values.confirmed) throw new Error("Confirme l'enregistrement de l'avertissement.");
        const result = await request(`/api/community/${guildId}/warn`, {data: {member_id: values.member_id.trim(), reason: values.reason.trim()}});
        toast(result.note); await loadModules();
      }});
  };
}

async function loadInteractive() {
  if (!app.selected) return;
  const id = app.selected;
  try {
    const events = await request(`/api/interactive/${id}`);
    if (app.selected === id) app.interactiveData = events;
  } catch (e) { toast(e.message, true); }
  renderInteractive();
}

function renderInteractive() {
  const channels = (app.details?.channels || []).filter(c => c.type === "text");
  ["pollChannel", "giveawayChannel", "quizChannel"].forEach(id => {
    const node = $(id), current = node.value;
    const empty = dom("option", "", "Choisir un salon"); empty.value = "";
    replace(node, [empty, ...channels.map(channel => {
      const option = dom("option", "", channel.name); option.value = channel.id; return option;
    })]);
    node.value = current && channels.some(c => c.id === current) ? current : "";
  });
  for (const id of ["pollForm", "giveawayForm", "quizForm"]) {
    $(id).querySelector("button[type=submit]").disabled = !app.bootstrap?.online || !channels.length;
  }
  const data = app.interactiveData;
  if (!data) { replace($("interactiveHistory"), [dom("p", "empty", "Aucun événement chargé.")]); return; }
  const events = [...data.events].reverse();
  const nodes = events.map(e => {
    const row = dom("div", "module-rank");
    const subject = e.type === "poll" || e.type === "quiz" ? e.question : e.prize;
    const state = e.status === "closed" ? "Terminé" : "En cours";
    row.append(dom("strong", "", `${e.type === "poll" ? "📊" : e.type === "quiz" ? "🧠" : "🎁"} ${subject}`),
               dom("span", "", `${state} · ${new Date(e.ends_at * 1000).toLocaleString("fr-FR")}`));
    if (e.result) row.append(dom("small", "", e.type === "poll" ? `Votes : ${e.result.votes.join(" / ")}` : e.type === "quiz" ? `Bonnes réponses : ${e.result.correct} / ${e.result.participants}` : `Participants : ${e.result.participants} · Gagnant : ${e.result.winner_id || "aucun"}`));
    return row;
  });
  const tickets = data.tickets || [];
  if (tickets.length) nodes.unshift(dom("p", "module-description", `🎟️ ${tickets.filter(t => t.status === "open").length} ticket(s) ouvert(s) / ${tickets.length} au total.`));
  const applications = data.applications || [];
  if (applications.length) nodes.unshift(dom("p", "module-description", `📝 ${applications.filter(a => a.status === "pending").length} candidature(s) en attente sur ${applications.length}.`));
  replace($("interactiveHistory"), nodes.length ? nodes : [dom("p", "empty", "Pas encore de sondage ni de giveaway sur ce serveur.")]);
}

function publishTicketPanel() {
  if (!app.selected) return;
  modal({title: "Publier le panneau de tickets", description: "Un message avec un bouton sera publié dans le salon choisi. Les membres pourront créer un salon privé lorsqu'ils cliqueront dessus, si le bot est en ligne.",
    confirmText: "Publier", onConfirm: async () => {
      await request(`/api/interactive/${app.selected}/tickets/panel`, {data: {}});
      toast("Panneau de tickets publié sur Discord."); await loadInteractive();
    }});
}

function publishApplicationPanel() {
  if (!app.selected) return;
  modal({title: "Publier le formulaire de candidature", description: "Un bouton ouvre un formulaire Discord. Les réponses sont envoyées uniquement dans le salon privé de candidature configuré.",
    confirmText: "Publier", onConfirm: async () => {
      await request(`/api/interactive/${app.selected}/applications/panel`, {data: {}});
      toast("Formulaire de candidature publié sur Discord."); await loadInteractive();
    }});
}

function createInteractive(kind) {
  if (!app.selected) return toast("Sélectionne un serveur.", true);
  const data = kind === "poll" || kind === "quiz" ? {
    channel_id: $("pollChannel").value, question: $("pollQuestion").value.trim(),
    options: $("pollOptions").value.split(/\r?\n/).map(x => x.trim()).filter(Boolean),
    minutes: Number($("pollMinutes").value),
  } : {channel_id: $("giveawayChannel").value,
       prize: $("giveawayPrize").value.trim(), minutes: Number($("giveawayMinutes").value)};
  if (kind === "quiz") {
    data.channel_id = $("quizChannel").value;
    data.question = $("quizQuestion").value.trim();
    data.options = $("quizOptions").value.split(/\r?\n/).map(x => x.trim()).filter(Boolean);
    data.minutes = Number($("quizMinutes").value);
    data.correct_index = Number($("quizCorrect").value) - 1;
  }
  const channel = (app.details?.channels || []).find(c => c.id === data.channel_id);
  if (!channel) return toast("Choisis un salon textuel disponible.", true);
  modal({title: kind === "poll" ? "Publier le sondage ?" : kind === "quiz" ? "Lancer le quiz ?" : "Lancer le giveaway ?",
    description: `Publication réelle dans #${channel.name} sur ${currentGuild()?.name || "ce serveur"}. Les réactions seront ouvertes pendant ${data.minutes} minute(s).`,
    confirmText: "Publier maintenant", onConfirm: async () => {
      await request(`/api/interactive/${app.selected}/${kind}`, {data});
      toast(kind === "poll" ? "Sondage publié sur Discord." : kind === "quiz" ? "Quiz publié sur Discord." : "Giveaway lancé sur Discord.");
      await loadInteractive();
    }});
}

async function loadCatalog() {
  try {
    app.catalog = await request("/api/catalog");
    const categories = [...new Set(app.catalog.features.map(f => f.category))];
    const allCategories = dom("option", "", "Toutes les catégories"); allCategories.value = "";
    replace($("catalogCategory"), [allCategories, ...categories.map(name => {
      const option = dom("option", "", name); option.value = name; return option;
    })]);
    renderCatalog(); renderPlan();
  } catch (e) {
    replace($("catalogGrid"), [dom("p", "empty", "Catalogue indisponible : " + e.message)]);
  }
}

function renderCatalog() {
  const query = $("catalogSearch").value.trim().toLocaleLowerCase("fr-FR");
  const category = $("catalogCategory").value;
  const onlyExternal = $("catalogExternalOnly").checked;
  const features = app.catalog.features.filter(f => {
    const provider = app.catalog.providers[f.provider_id];
    return (!category || f.category === category) && (!onlyExternal || Boolean(provider)) &&
      `${f.title} ${f.category} ${provider?.name || ""}`.toLocaleLowerCase("fr-FR").includes(query);
  });
  $("catalogCount").textContent = `${features.length} / ${app.catalog.features.length} FONCTIONNALITÉS`;
  const cards = features.map(f => {
    const provider = app.catalog.providers[f.provider_id];
    const card = dom("article", "catalog-card");
    const header = dom("div", "catalog-card-head");
    header.append(dom("span", "catalog-icon", f.icon), dom("span", "catalog-number", `#${String(f.number).padStart(2, "0")}`));
    card.append(header, dom("strong", "", f.title), dom("small", "catalog-category", f.category));
    if (f.availability === "native") {
      card.append(dom("p", "catalog-provider", "✓ Module natif à configurer dans Discord Pilot"));
      const configure = dom("button", "primary-button", "Configurer le module");
      configure.onclick = () => { switchTab("modules"); loadModules(); };
      card.append(configure);
      if (provider) card.append(dom("small", "catalog-category", `Alternative externe : ${provider.name}`));
    } else if (provider) {
      card.append(dom("p", "catalog-provider", `Bot conseillé : ${provider.name}`));
      const actions = dom("div", "catalog-actions");
      const prepare = dom("button", "primary-button", "Préparer l'ajout");
      prepare.onclick = () => prepareIntegration(f.provider_id);
      const link = dom("a", "outline-button", "Site officiel ↗");
      link.href = provider.url; link.target = "_blank"; link.rel = "noopener noreferrer";
      actions.append(prepare, link); card.append(actions);
    } else {
      card.append(dom("p", "catalog-planned", "Idée à développer · aucune installation automatique disponible"));
    }
    return card;
  });
  replace($("catalogGrid"), cards.length ? cards : [dom("p", "empty", "Aucune fonctionnalité ne correspond à cette recherche.")]);
}

async function prepareIntegration(providerId) {
  if (!app.selected) return toast("Sélectionne d'abord un serveur dans la colonne de gauche.", true);
  try {
    const data = await request("/api/integrations/plan", {data: {guild_id: app.selected, provider: providerId}});
    app.plan = data.plan;
    switchTab("studio"); renderPlan(); await loadHistory();
    $("planPanel").scrollIntoView({behavior: "smooth", block: "center"});
    toast("Plan prêt. L'installation nécessite ton autorisation sur le site officiel.");
  } catch (e) { toast(e.message, true); }
}

function addServer() {
  modal({title: "Ajouter un serveur", description: "Renseigne son identifiant Discord. Il sera épinglé ici, et accessible dès que ton bot y sera présent.",
    fields: [{id: "id", label: "Identifiant du serveur", placeholder: "Ex. : 123456789012345678"}, {id: "alias", label: "Nom dans l'application", placeholder: "Ex. : Mon serveur"}], confirmText: "Ajouter", onConfirm: async ({id, alias}) => {
      if (!/^\d{17,20}$/.test(id)) throw new Error("L'identifiant doit contenir 17 à 20 chiffres.");
      await request("/api/alias", {data: {guild_id: id, alias: alias.trim() || known[id] || `Serveur ${id.slice(-6)}`}});
      await bootstrap(); await selectGuild(id); toast("Serveur ajouté à l'espace de travail.");
    }});
}

function renameAlias() {
  const g = currentGuild(); if (!g) return;
  modal({title: "Nom du serveur", description: "Cette modification concerne uniquement ton tableau de bord, pas Discord.",
    fields: [{id: "alias", label: "Nom personnalisé", value: g.alias || g.name}], confirmText: "Enregistrer", onConfirm: async ({alias}) => {
      await request("/api/alias", {data: {guild_id: g.id, alias}}); await bootstrap(); toast("Nom enregistré.");
    }});
}

function settings() {
  modal({title: "Connecter mon bot", description: "Dans Discord Developer Portal, ouvre ton application > Bot > Reset Token. Copie ce nouveau token (pas l'Application ID ni le Client Secret). Ne le partage avec personne.",
    fields: [
      {id: "token", label: "Token secret du bot", type: "password", placeholder: "Colle le token Discord ici", autocomplete: "off"},
      {id: "remember", type: "checkbox", label: "Mémoriser sur ce PC (chiffré avec Windows DPAPI)"},
      {type: "info", text: "Seules les permissions Gérer les salons et Gérer les rôles sont utiles pour la structure. Le bot doit avoir été invité dans les serveurs concernés."}
    ], confirmText: "Connecter le bot", onConfirm: async ({token, remember}) => {
      if (!token.trim()) throw new Error("Colle le nouveau token de l'onglet Bot.");
      $("modalConfirm").textContent = "Vérification auprès de Discord…";
      try {
        await request("/api/connect", {data: {token, remember}});
        const status = await waitForDiscordConnection();
        await bootstrap();
        toast(`Bot connecté à ${status.guilds.length} serveur(s).`);
      } finally {
        $("modalConfirm").textContent = "Connecter le bot";
        await bootstrap(true);
      }
    }});
  if (app.bootstrap?.online) {
    const button = dom("button", "outline-button", "Déconnecter et oublier le token");
    button.style.marginTop = "16px";
    button.onclick = async () => {
      try { await request("/api/disconnect", {data: {}}); $("modalBackdrop").hidden = true; await bootstrap(); toast("Bot déconnecté et token mémorisé effacé."); }
      catch (e) { toast(e.message, true); }
    };
    $("modalBody").append(button);
  }
}

function renderLiveTest(report) {
  const status = $("liveTestResults");
  status.hidden = false;
  const title = report.status === "verified" ? "✓ Vérifications réussies sur Discord" :
                report.status === "warning" ? "⚠ Vérifications avec avertissements" :
                "✕ Vérifications incomplètes sur Discord";
  const header = dom("strong", "", title);
  const list = dom("ul", "");
  (report.checks || []).forEach(check => {
    const li = dom("li", "", `${check.ok ? "✓" : "✕"} ${check.name} — ${check.detail}`);
    list.append(li);
  });
  replace(status, [header, list]);
}

function testDiscord() {
  if (!app.selected) return toast("Sélectionne un serveur Discord.", true);
  modal({title: "Tester ton bot sur Discord", description: "Le test utilise la connexion réelle du bot dans ton application Windows. Il ne peut pas être effectué avec un bot déconnecté.",
    fields: [
      {id: "mode", type: "select", label: "Type de test", value: "read_only", options: [
        {value: "read_only", label: "Lecture réelle des salons et rôles (aucune modification)"},
        {value: "active", label: "Test complet : salon privé temporaire, message, lecture puis suppression"}
      ]},
      {type: "info", text: "Le test complet crée puis supprime uniquement un salon privé temporaire. Si la suppression échoue, son ID sera affiché pour nettoyage manuel."}
    ], confirmText: "Lancer le diagnostic", onConfirm: async ({mode}) => {
      const report = await request("/api/live-test", {data: {guild_id: app.selected, mode}});
      renderLiveTest(report);
      toast(report.status === "verified" ? "Diagnostic connecté réussi." : "Diagnostic terminé avec des vérifications à corriger.", report.status !== "verified");
    }});
}

async function createPlan() {
  if (!app.selected) return toast("Sélectionne un serveur.", true);
  if (app.busy) return;
  const requestedGuild = app.selected;
  const prompt = $("requestText").value.trim(); if (!prompt) return toast("Décris les changements à effectuer.", true);
  if (prompt.length > 50000) return toast("La limite est de 50 000 caractères.", true);
  app.busy = true; $("generateButton").textContent = "Analyse de la demande…"; renderOverview();
  try {
    const data = await request("/api/plan", {data: {guild_id: app.selected, prompt, mode: $("modeSelect").value, model: $("modelSelect").value || undefined}});
    if (app.selected !== requestedGuild) {
      toast("Le plan a été enregistré sur le serveur d'origine. Rouvre ce serveur pour le retrouver.");
      return;
    }
    if (data.configuration_required === "channel_role_access") {
      toast(data.message);
      await openChannelRolePermissions();
      return;
    }
    if (data.needs_clarification) {
      const examples = (data.examples || []).slice(0, 3).join(" · ");
      modal({title: "Préciser la demande", description: data.question || "Quel changement précis veux-tu faire ?",
        fields: [
          {type: "info", text: `Aucune modification effectuée. Exemples : ${examples}`},
          {id: "instruction", type: "textarea", label: "Demande d'origine (modifiable)", value: prompt,
           placeholder: "Par exemple « Crée un salon annonces »"},
          {id: "detail", type: "textarea", label: "Réponse ou précision supplémentaire (facultative)",
           placeholder: "Par exemple « le rôle Membre, uniquement sur #annonces »"}
        ], confirmText: "Préparer ce plan", onConfirm: async ({instruction, detail}) => {
          const revised = instruction.trim();
          const extra = (detail || "").trim();
          if (revised.length < 3 || (revised === prompt && !extra))
            throw new Error("Reformule la demande ou réponds à la question de l'IA.");
          const full = extra ? `${revised}\nPrécision : ${extra}` : revised;
          if (full.length > 50000) throw new Error("Ta demande dépasse 50 000 caractères.");
          $("requestText").value = full;
          updateRequestLength();
          setTimeout(() => createPlan(), 0);
        }});
      return;
    }
    app.plan = data.plan;
    $("requestText").value = data.plan.prompt; // Remove old clarification lines.
    updateRequestLength();
    renderPlan(); await loadHistory();
    $("planPanel").scrollIntoView({behavior: "smooth", block: "nearest"}); toast("Plan créé. Vérifie les actions avant de valider.");
  } catch (e) { toast(e.message, true); }
  finally { app.busy = false; $("generateButton").textContent = "✦ Préparer le plan  →"; renderOverview(); }
}

async function openChannelRolePermissions() {
  if (!app.selected) return toast("Sélectionne un serveur.", true);
  const guildId = app.selected;
  const context = await request(`/api/permissions/${guildId}`);
  if (!context.channels.length || !context.roles.length) return toast("Ce serveur n'a pas les salons ou rôles nécessaires.", true);
  const recent = context.recent_channels || [];
  const scopes = [
    ...(recent.length ? [{value: "recent", label: `Les ${recent.length} salon(s) de la dernière création réussie`}] : []),
    ...context.channels.map(c => ({value: c.id, label: `${c.type === "voice" ? "🔊" : "#"} ${c.name}`}))
  ];
  const options = [{value: "keep", label: "Ne pas modifier"}, {value: "allow", label: "Autoriser"},
                   {value: "deny", label: "Refuser"}, {value: "inherit", label: "Revenir à l'héritage"}];
  modal({title: "Permissions des salons", description: "Choisis un rôle et ce qu'il peut voir ou faire. Pour les salons vocaux, « Écrire/Rejoindre » gère la connexion. Les accès à @everyone peuvent exposer des salons privés. Une prévisualisation doit encore être validée avant toute modification.",
    fields: [
      {id: "scope", type: "select", label: "Salon(s) à configurer", options: scopes, value: recent.length ? "recent" : context.channels[0].id},
      {id: "role_id", type: "select", label: "Rôle concerné", options: [{value: "", label: "Choisir un rôle…"},
        ...context.roles.map(r => ({value: r.id, label: r.name}))]},
      {id: "view", type: "select", label: "Voir le salon", options},
      {id: "participate", type: "select", label: "Écrire / rejoindre un vocal", options},
      {id: "confirmed", type: "checkbox", checked: false, label: "Je confirme ces choix pour les salons et le rôle sélectionnés"}
    ], confirmText: "Préparer le plan", onConfirm: async values => {
      if (!values.confirmed) throw new Error("Confirme les paramètres choisis.");
      if (!values.role_id) throw new Error("Sélectionne un rôle.");
      if (values.view === "keep" && values.participate === "keep") throw new Error("Choisis au moins une permission à modifier.");
      const channels = values.scope === "recent" ? recent.map(c => c.id) : [values.scope];
      if (!channels.length) throw new Error("Aucun salon créé récemment n'est encore disponible.");
      const result = await request(`/api/permissions/${guildId}/draft`, {data: {
        channels, role_id: values.role_id, view: values.view, participate: values.participate
      }});
      app.plan = result.plan;
      switchTab("studio"); renderPlan(); await loadHistory();
      $("planPanel").scrollIntoView({behavior: "smooth", block: "nearest"});
      toast("Plan de permissions créé. Vérifie le rôle et les salons avant de valider.");
    }});
}

async function preset(id) {
  if (!app.selected) return toast("Sélectionne d'abord un serveur.", true);
  try { const data = await request("/api/preset", {data: {guild_id: app.selected, preset_id: id}}); app.plan = data.plan; switchTab("studio"); renderPlan(); await loadHistory(); $("planPanel").scrollIntoView({behavior: "smooth", block: "center"}); }
  catch (e) { toast(e.message, true); }
}

function renderPresets() {
  const templates = app.bootstrap?.presets || [];
  const nodes = [];
  for (const [i, t] of templates.entries()) {
    const b = dom("button", "preset-card");
    b.append(dom("span", "preset-icon", icons[i] || "✦"),
             dom("strong", "", t.label), dom("small", "", t.description));
    b.onclick = () => preset(t.id);
    nodes.push(b);
    if (t.id !== "vexora-esport") continue;
    const auditButton = dom("button", "outline-button", "🔍 Auditer les 56 éléments sur Discord");
    const output = dom("div", "module-description");
    auditButton.onclick = async () => {
      if (!app.selected) return toast("Sélectionne le véritable serveur Vexora.", true);
      const guildId = app.selected;
      auditButton.disabled = true;
      replace(output, [dom("p", "", "Lecture des salons et rôles Discord…")]);
      try {
        const result = await request(`/api/audit/${guildId}/vexora-esport`);
        if (app.selected !== guildId) {
          replace(output, [dom("p", "", "Le serveur a changé : recommence le contrôle.")]);
          return;
        }
        replace(output, [
          dom("strong", "", `${result.passed}/${result.expected} éléments vérifiés — ${result.status}`),
          dom("p", "", result.detail),
          ...(result.checks || []).filter(c => !c.ok).map(c =>
            dom("p", "", `✗ ${c.name} : ${c.detail}`)),
          dom("p", "", "Lecture seule ; les tickets et les permissions sont vérifiés séparément."),
        ]);
      } catch (e) {
        replace(output, [dom("p", "", `Audit impossible : ${e.message}`)]);
      } finally {
        auditButton.disabled = false;
      }
    };
    const auditCard = dom("div", "module-description");
    auditCard.append(auditButton, output);
    nodes.push(auditCard);
  }
  replace($("presetCards"), nodes);
}

function executePlan() {
  const p = app.plan, g = currentGuild(); if (!p || !g) return;
  const destructive = p.actions.some(a => a.type.startsWith("delete_"));
  const onlyExternal = p.actions.every(a => a.type === "suggest_integration");
  modal({title: destructive ? "Confirmer les suppressions" : onlyExternal ? "Préparer les installations externes ?" : "Appliquer ce plan ?", description: `${p.actions.length} action(s) pour ${g.name} (ID ${g.id}). Vérifie qu'il s'agit du bon serveur.${destructive ? " Certaines suppressions sont irréversibles." : ""}`,
    fields: destructive ? [{id: "name", label: "Saisis exactement le nom Discord du serveur", placeholder: g.name}] : [{type: "info", text: onlyExternal ? "Aucun bot externe ne sera installé maintenant. Discord Pilot affichera les liens officiels : il te faudra sélectionner le serveur et accepter les permissions dans Discord." : "Discord Pilot exécutera le plan dans l'ordre et enregistrera le résultat de chaque étape."}],
    confirmText: destructive ? "Confirmer la suppression" : onlyExternal ? "Préparer les liens" : "Exécuter maintenant", onConfirm: async ({name}) => {
      await request(`/api/execute/${p.id}`, {data: {confirm_delete_name: name || ""}}); toast("Exécution démarrée. Les résultats s'affichent en direct."); await loadHistory();
    }});
}

async function updatesMenu() {
  let status;
  try { status = await request("/api/update/status"); }
  catch (e) { return toast(e.message, true); }
  modal({
    title: "Mises à jour de Discord Pilot",
    description: `Version installée : ${status.version}. Le bouton MAJ vérifie les versions publiées sur GitHub, puis télécharge et installe la nouvelle version.`,
    fields: [
      {id: "update_url", label: "URL du manifeste de mise à jour (HTTPS GitHub)", value: status.url || "", placeholder: "https://raw.githubusercontent.com/.../update.json"},
      {type: "info", text: "Les paramètres et historiques sont conservés pendant les mises à jour. Le téléchargement est contrôlé par SHA-256 et l'ancienne version est sauvegardée. Ne ferme pas l'application pendant le téléchargement."}
    ],
    confirmText: "Fermer",
    onConfirm: async () => {}
  });
  const body = $("modalBody");
  const details = dom("div", "update-status", status.pending ? `Mise à jour ${status.pending.version} déjà téléchargée : installation possible.` : status.url ? "Source enregistrée. Clique sur Vérifier." : "Aucune source configurée : les mises à jour automatiques ne peuvent pas encore être recherchées.");
  body.append(details);
  const actions = dom("div", "update-row");
  const save = dom("button", "outline-button", "Enregistrer la source");
  const check = dom("button", "outline-button", "↻ Vérifier");
  const download = dom("button", "primary-button", "↓ Télécharger"); download.hidden = true;
  const install = dom("button", "primary-button", "Installer et redémarrer"); install.hidden = !status.pending;
  let latest = null;

  save.onclick = async () => {
    try {
      const url = $("modal-update_url").value.trim();
      const result = await request("/api/update/source", {data: {url}});
      details.textContent = url ? "Source enregistrée. Tu peux maintenant vérifier les nouvelles versions." : "Source GitHub par défaut rétablie.";
      $("modal-update_url").value = result.url;
      toast("Source des mises à jour enregistrée.");
    } catch (e) { toast(e.message, true); }
  };
  check.onclick = async () => {
    check.disabled = true; details.textContent = "Vérification du manifeste GitHub…";
    try {
      const result = await request("/api/update/check", {data: {}});
      latest = result.update;
      if (latest.available) {
        app.updateAvailable = true;
        details.classList.add("good");
        details.textContent = `Nouvelle version ${latest.version} disponible. Téléchargement vérifié par SHA-256.`;
        download.hidden = false;
        download.textContent = `↓ Télécharger ${latest.version}`;
        $("updateButton").classList.add("available");
      } else { app.updateAvailable = false; details.textContent = `Tu as déjà la dernière version publiée (${latest.version}).`; download.hidden = true; }
    } catch (e) { details.textContent = e.message; toast(e.message, true); }
    finally { check.disabled = false; }
  };
  download.onclick = async () => {
    download.disabled = true; details.textContent = "Téléchargement sécurisé et vérification du programme…";
    try {
      const r = await request("/api/update/download", {data: {}});
      status.pending = r.pending;
      details.textContent = `Version ${r.pending.version} vérifiée et prête à installer.`;
      install.hidden = false;
      download.hidden = true;
    } catch (e) { details.textContent = e.message; toast(e.message, true); }
    finally { download.disabled = false; }
  };
  install.onclick = async () => {
    install.disabled = true;
    try {
      const previousVersion = status.version;
      const targetVersion = status.pending?.version;
      if (!targetVersion) throw new Error("Aucune mise à jour prête à installer.");
      // The server may close just before the HTTP response reaches the browser.
      // In that case, keep watching for the new version instead of reporting a network error.
      try { await request("/api/update/apply", {data: {}}); }
      catch (error) {
        if (!/connexion locale interrompue/i.test(error.message)) throw error;
      }
      $("modalBackdrop").hidden = true;
      toast("Installation en cours… La page se reconnectera automatiquement.");
      await waitForVersion(previousVersion, targetVersion);
    } catch (e) { install.disabled = false; toast(e.message, true); }
  };
  actions.append(save, check);
  body.append(actions);
  const extra = dom("div", "update-row");
  const choose = dom("button", "outline-button", "Importer un ZIP local");
  const picker = dom("input"); picker.type = "file"; picker.accept = ".zip,application/zip"; picker.hidden = true;
  choose.hidden = Boolean(status.standalone_exe);
  choose.onclick = () => picker.click();
  picker.onchange = async () => {
    const file = picker.files?.[0]; if (!file) return;
    choose.disabled = true; details.textContent = "Validation du ZIP local…";
    try {
      const form = new FormData(); form.append("file", file);
      const r = await request("/api/update/import", {method: "POST", body: form});
      status.pending = r.pending;
      details.textContent = `Archive version ${r.pending.version} vérifiée. Installation possible.`;
      install.hidden = false;
    } catch (e) { details.textContent = e.message; toast(e.message, true); }
    finally { choose.disabled = false; picker.value = ""; }
  };
  extra.append(choose, install, picker);
  body.append(extra, download);
}

async function probeVersionOnCurrentPort(expectedVersion) {
  const response = await fetch(`/api/bootstrap?probe=${Date.now()}`, {
    cache: "no-store", signal: AbortSignal.timeout(2300),
  });
  if (!response.ok) return false;
  const data = await response.json();
  if (data.version !== expectedVersion) return false;
  // Check that static files are served too before navigating to the new page.
  const assets = await fetch(`/assets/app.js?probe=${Date.now()}`, {
    cache: "no-store", signal: AbortSignal.timeout(2300),
  });
  return assets.ok;
}

async function findRestartedPort(expectedVersion) {
  const originalPort = Number(window.location.port || 80);
  const hostname = window.location.hostname;
  if (!Number.isInteger(originalPort) || originalPort < 1 || originalPort > 65530 || !["127.0.0.1", "localhost"].includes(hostname)) return null;
  // Only a minimal /api/health endpoint exposes CORS to other loopback ports.
  const ports = Array.from({length: 5}, (_, i) => originalPort + i + 1);
  const probes = ports.map(async port => {
    try {
      const origin = `${window.location.protocol}//${hostname}:${port}`;
      const response = await fetch(`${origin}/api/health?probe=${Date.now()}`, {
        cache: "no-store", signal: AbortSignal.timeout(1000),
      });
      if (!response.ok) return null;
      const health = await response.json();
      return health.discord_pilot === true && health.version === expectedVersion ? origin : null;
    } catch { return null; }
  });
  return (await Promise.all(probes)).find(Boolean) || null;
}

async function waitForVersion(previousVersion, expectedVersion) {
  await delay(1400);
  const deadline = Date.now() + 180000;
  let consecutiveReady = 0;
  let lastAlternative = null;
  let alternativeReady = 0;
  let attempt = 0;
  while (Date.now() < deadline) {
    try {
      if (expectedVersion !== previousVersion && await probeVersionOnCurrentPort(expectedVersion)) {
        consecutiveReady += 1;
        if (consecutiveReady >= 2) {
          // Only refresh after the new HTTP server has proved it is stable.
          window.location.replace(`${window.location.pathname}?updated=${Date.now()}`);
          return;
        }
      } else { consecutiveReady = 0; }
    } catch { consecutiveReady = 0; }
    if (attempt % 4 === 0) {
      const alternative = await findRestartedPort(expectedVersion);
      if (alternative) {
        alternativeReady = alternative === lastAlternative ? alternativeReady + 1 : 1;
        lastAlternative = alternative;
        if (alternativeReady >= 2) {
          window.location.replace(`${alternative}/?updated=${Date.now()}`);
          return;
        }
      } else { alternativeReady = 0; }
    }
    attempt += 1;
    await delay(1000);
  }
  toast("Mise à jour non confirmée. Discord Pilot se reconnectera dès que le serveur sera disponible. Consulte le journal updater.log ou launcher.log dans %LOCALAPPDATA%\\DiscordPilot.", true);
}

async function backgroundUpdateCheck() {
  if (!app.bootstrap?.update_url || app.bootstrap?.update_pending) return;
  try {
    const result = await request("/api/update/check", {data: {}});
    app.updateAvailable = Boolean(result.update.available);
    $("updateButton").classList.toggle("available", app.updateAvailable);
  } catch { /* Silence : la source peut être temporairement inaccessible. */ }
}

async function init() {
  $("modalClose").onclick = $("modalCancel").onclick = () => $("modalBackdrop").hidden = true;
  $("modalBackdrop").addEventListener("click", (e) => { if (e.target.id === "modalBackdrop") $("modalBackdrop").hidden = true; });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("modalBackdrop").hidden = true; });
  $("addServer").onclick = addServer;
  $("settingsButton").onclick = settings;
  $("updateButton").onclick = updatesMenu;
  $("aliasButton").onclick = renameAlias;
  $("guildSearch").oninput = renderGuilds;
  $("refreshButton").onclick = () => { loadDetails(); loadHistory(); toast("Actualisation lancée."); };
  $("structureRefresh").onclick = loadDetails;
  $("generateButton").onclick = createPlan;
  $("requestText").addEventListener("input", updateRequestLength);
  $("testDiscordButton").onclick = testDiscord;
  $("voiceButton").onclick = () => toggleVoiceRecording($("requestText"));
  initializeUniversalVoice();
  $("executeButton").onclick = executePlan;
  $("modeSelect").onchange = () => $("modelSelect").hidden = !app.models.length || $("modeSelect").value === "local";
  $("inviteButton").onclick = async () => { try { const data = await request("/api/invite"); window.open(data.url, "_blank", "noopener,noreferrer"); } catch (e) { toast(e.message, true); } };
  $("exportHistory").onclick = () => { if (app.selected) window.location.href = `/api/export/${app.selected}`; };
  $("catalogSearch").oninput = renderCatalog;
  $("catalogCategory").onchange = renderCatalog;
  $("catalogExternalOnly").onchange = renderCatalog;
  $("refreshModules").onclick = async () => { await loadDetails(); await Promise.all([loadModules(), loadInteractive()]); };
  $("configureChannelRoles").onclick = async () => { try { await openChannelRolePermissions(); } catch(e) { toast(e.message, true); } };
  $("pollForm").onsubmit = e => { e.preventDefault(); createInteractive("poll"); };
  $("giveawayForm").onsubmit = e => { e.preventDefault(); createInteractive("giveaway"); };
  $("quizForm").onsubmit = e => { e.preventDefault(); createInteractive("quiz"); };
  document.querySelectorAll(".tab").forEach(t => t.onclick = () => switchTab(t.dataset.tab));
  document.querySelectorAll("[data-example]").forEach(t => t.onclick = () => { $("requestText").value = t.dataset.example; updateRequestLength(); switchTab("studio"); $("requestText").focus(); });
  updateRequestLength();
  await bootstrap(); renderPresets(); await loadCatalog(); await models();
  backgroundUpdateCheck();
  setInterval(async () => {
    await bootstrap(true);
    if (app.plan && ["queued", "running"].includes(app.plan.status)) await loadHistory();
  }, 1800);
  setInterval(models, 25000);
  setInterval(backgroundUpdateCheck, 6 * 60 * 60 * 1000);
}

init();
