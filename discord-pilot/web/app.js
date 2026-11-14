"use strict";

const $ = (id) => document.getElementById(id);
const app = { csrf: "", bootstrap: null, selected: localStorage.getItem("pilotGuild") || "", details: null, history: [], plan: null, tab: "studio", models: [], busy: false, updateAvailable: false };
// No personal server identifiers are shipped in public updates; Discord provides real names after login.
const known = {};
const actionNames = { create_category: "Créer une catégorie", create_text_channel: "Créer un salon textuel", create_voice_channel: "Créer un salon vocal", create_role: "Créer un rôle", rename_channel: "Renommer un salon", rename_role: "Renommer un rôle", set_topic: "Modifier la description", send_message: "Publier un message", make_private: "Rendre un salon privé", delete_channel: "SUPPRIMER UN SALON", delete_role: "SUPPRIMER UN RÔLE" };
const icons = ["⌂", "♧", "♜", "▤"];
let serverWasUnavailable = false;
const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));

function dom(tag, className, value) { const node = document.createElement(tag); if (className) node.className = className; if (value !== undefined) node.textContent = String(value); return node; }
function replace(node, children) { node.replaceChildren(...children); }
function abbreviate(s) { return (s || "S").split(/\s+/).filter(Boolean).slice(0, 2).map(x => x[0]).join("").toUpperCase(); }
function time(iso) { try { return new Date(iso).toLocaleString("fr-FR", {dateStyle: "medium", timeStyle: "short"}); } catch { return ""; } }

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
    const label = dom("label", "modal-label", f.label); const inp = dom("input", "modal-input"); inp.id = `modal-${f.id}`;
    inp.type = f.type || "text"; inp.placeholder = f.placeholder || ""; inp.value = f.value || ""; inp.autocomplete = f.autocomplete || "off";
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
  app.selected = id; app.details = null; app.history = []; app.plan = null;
  localStorage.setItem("pilotGuild", id);
  $("planPanel").hidden = true;
  renderGuilds(); renderOverview();
  await Promise.all([loadDetails(), loadHistory()]);
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
    const name = dom("div"); name.append(dom("strong", "", p.prompt), dom("small", "", `${time(p.created_at)} · ${p.mode} · ${p.actions.length} action(s)`));
    const badge = dom("span", `pill ${p.status === "completed" ? "success" : ["failed", "partial"].includes(p.status) ? "failed" : ""}`, stateName(p.status));
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

function stateName(s) { return ({draft: "Brouillon", queued: "En attente", running: "En cours", completed: "Terminé", partial: "Partiellement terminé", failed: "Échec", done: "Réussi", skipped: "Déjà présent"})[s] || s; }
function actionDescription(a) {
  let text = `${actionNames[a.type] || a.type} · ${a.channel || a.name || ""}`;
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
  $("planTitle").textContent = `${p.actions.length} action${p.actions.length > 1 ? "s" : ""} à ${p.status === "draft" ? "valider" : "suivre"}`;
  $("planMeta").textContent = `Serveur : ${currentGuild()?.name || p.guild_id} · ${p.mode}`;
  $("planBadge").textContent = stateName(p.status);
  $("planBadge").className = `pill ${p.status === "completed" ? "success" : ["failed", "partial"].includes(p.status) ? "failed" : ""}`;
  replace($("planActions"), p.actions.map((a, i) => {
    const li = dom("li"); const num = dom("span", "step-num", i + 1);
    const words = dom("div", "step-text"); words.append(dom("strong", "", actionDescription(a)));
    const result = (p.results || []).find(r => r.index === i);
    if (result) words.append(dom("small", "", result.detail));
    const marker = dom("span", `step-state ${result?.status || ""}`, result ? stateName(result.status) : a.type.startsWith("delete_") ? "Attention" : "À faire");
    li.append(num, words, marker); return li;
  }));
  $("executeButton").disabled = p.status !== "draft" || !app.bootstrap?.online || !app.bootstrap.guilds.some(g => g.id === p.guild_id);
  $("executeButton").textContent = p.status === "draft" ? "Appliquer sur Discord ↗" : stateName(p.status);
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
    $("inviteButton").disabled = !data.online;
    $("updateVersion").textContent = `v${data.version || "?"}`;
    $("updateButton").classList.toggle("available", Boolean(data.update_pending) || app.updateAvailable);
    if (data.error && !quiet) toast(data.error, true);
    if (!app.selected && guilds().length) app.selected = guilds()[0].id;
    renderGuilds(); renderOverview();
    if (wasOnline !== data.online || (!quiet && app.selected)) await Promise.all([loadDetails(), loadHistory()]);
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
    $("ollamaStatus").textContent = data.available ? `✦ IA locale active · ${data.models.length} modèle(s)` : "✓ Assistant intégré actif : commandes courantes sans installation";
    replace($("modelSelect"), data.models.map(name => { const opt = dom("option", "", name); opt.value = name; return opt; }));
    $("modelSelect").hidden = !data.available || $("modeSelect").value === "local";
  } catch { $("ollamaStatus").textContent = "Mode sans IA disponible"; }
}

function switchTab(key) {
  app.tab = key;
  document.querySelectorAll(".tab").forEach(b => b.classList.toggle("active", b.dataset.tab === key));
  ["studio", "structure", "history"].forEach(k => $(`${k}Tab`).hidden = k !== key);
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

async function createPlan() {
  if (!app.selected) return toast("Sélectionne un serveur.", true);
  const prompt = $("requestText").value.trim(); if (!prompt) return toast("Décris les changements à effectuer.", true);
  app.busy = true; $("generateButton").textContent = "Analyse de la demande…"; renderOverview();
  try {
    const data = await request("/api/plan", {data: {guild_id: app.selected, prompt, mode: $("modeSelect").value, model: $("modelSelect").value || undefined}});
    if (data.needs_clarification) throw new Error(data.question || "Décris une modification précise.");
    app.plan = data.plan;
    $("requestText").value = data.plan.prompt; // Remove old clarification lines.
    renderPlan(); await loadHistory();
    $("planPanel").scrollIntoView({behavior: "smooth", block: "nearest"}); toast("Plan créé. Vérifie les actions avant de valider.");
  } catch (e) { toast(e.message, true); }
  finally { app.busy = false; $("generateButton").textContent = "✦ Préparer le plan  →"; renderOverview(); }
}

async function preset(id) {
  if (!app.selected) return toast("Sélectionne d'abord un serveur.", true);
  try { const data = await request("/api/preset", {data: {guild_id: app.selected, preset_id: id}}); app.plan = data.plan; switchTab("studio"); renderPlan(); await loadHistory(); $("planPanel").scrollIntoView({behavior: "smooth", block: "center"}); }
  catch (e) { toast(e.message, true); }
}

function renderPresets() {
  const templates = app.bootstrap?.presets || [];
  replace($("presetCards"), templates.map((t, i) => { const b = dom("button", "preset-card"); b.append(dom("span", "preset-icon", icons[i] || "✦"), dom("strong", "", t.label), dom("small", "", t.description)); b.onclick = () => preset(t.id); return b; }));
}

function executePlan() {
  const p = app.plan, g = currentGuild(); if (!p || !g) return;
  const destructive = p.actions.some(a => a.type.startsWith("delete_"));
  modal({title: destructive ? "Confirmer les suppressions" : "Appliquer ce plan ?", description: `${p.actions.length} action(s) vont être réalisées sur ${g.name} (ID ${g.id}). Vérifie qu'il s'agit du bon serveur.${destructive ? " Certaines suppressions sont irréversibles." : ""}`,
    fields: destructive ? [{id: "name", label: "Saisis exactement le nom Discord du serveur", placeholder: g.name}] : [{type: "info", text: "Discord Pilot exécutera le plan dans l'ordre et enregistrera le résultat de chaque étape."}],
    confirmText: destructive ? "Confirmer la suppression" : "Exécuter maintenant", onConfirm: async ({name}) => {
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
  $("executeButton").onclick = executePlan;
  $("modeSelect").onchange = () => $("modelSelect").hidden = !app.models.length || $("modeSelect").value === "local";
  $("inviteButton").onclick = async () => { try { const data = await request("/api/invite"); window.open(data.url, "_blank", "noopener,noreferrer"); } catch (e) { toast(e.message, true); } };
  $("exportHistory").onclick = () => { if (app.selected) window.location.href = `/api/export/${app.selected}`; };
  document.querySelectorAll(".tab").forEach(t => t.onclick = () => switchTab(t.dataset.tab));
  document.querySelectorAll("[data-example]").forEach(t => t.onclick = () => { $("requestText").value = t.dataset.example; switchTab("studio"); $("requestText").focus(); });
  await bootstrap(); renderPresets(); await models();
  backgroundUpdateCheck();
  setInterval(async () => {
    await bootstrap(true);
    if (app.plan && ["queued", "running"].includes(app.plan.status)) await loadHistory();
  }, 1800);
  setInterval(models, 25000);
  setInterval(backgroundUpdateCheck, 6 * 60 * 60 * 1000);
}

init();
