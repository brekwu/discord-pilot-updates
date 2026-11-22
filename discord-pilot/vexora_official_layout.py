"""Canonical EXISTING Vexora Esport Discord layout, not a new create preset.

Source: brekwu/discord-chatgpt-bridge/vexora_esports_setup.py
The local relay actually applied 32 base roles, 11 categories and 73 rooms
on 2026-11-20; 13 more roles were applied 2026-11-21.
Never recreate this layout using the generic Discord Pilot 56-action template.
"""
from __future__ import annotations

OFFICIAL_GUILD_ID = "1509985472921735168"
BASE_ROLES = [
  "👑 Fondateur",
  "💎 Direction Vexora",
  "⚙️ Responsable Esport",
  "🚀 Manager Rocket League",
  "🏗️ Manager Fortnite",
  "🎯 Manager Valorant",
  "⚔️ Manager Clash of Clans",
  "🎓 Coach Rocket League",
  "🎓 Coach Fortnite",
  "🎓 Coach Valorant",
  "🎓 Coach Clash of Clans",
  "📊 Analyste",
  "📋 Team Manager",
  "🚀 Joueur Rocket League",
  "🏗️ Joueur Fortnite",
  "🎯 Joueur Valorant",
  "⚔️ Joueur Clash of Clans",
  "⭐ Capitaine",
  "🧪 Joueur en essai",
  "🏆 Joueur Vexora",
  "📢 Communication",
  "🎬 Créateur de contenu",
  "🤝 Partenariats",
  "🛡️ Modérateur",
  "🛠️ Support",
  "💜 Supporter Vexora",
  "🎮 Rocket League",
  "🏗️ Fortnite",
  "🎯 Valorant",
  "⚔️ Clash of Clans",
  "🎟️ Candidat Esport",
  "🤖 Bot"
]
EXTRA_ROLES = [
  "🧭 Manager Esport",
  "🚀 Roster Rocket League",
  "⭐ Capitaine Rocket League",
  "🧪 Essai Rocket League",
  "🏗️ Roster Fortnite",
  "⭐ Capitaine Fortnite",
  "🧪 Essai Fortnite",
  "🎯 Roster Valorant",
  "⭐ Capitaine Valorant",
  "🧪 Essai Valorant",
  "⚔️ Roster Clash of Clans",
  "⭐ Capitaine Clash of Clans",
  "🧪 Essai Clash of Clans"
]
CATEGORIES = [
  "🏆 VEXORA ESPORTS",
  "🚀 ROCKET LEAGUE",
  "🏗️ FORTNITE",
  "🎯 VALORANT",
  "⚔️ CLASH OF CLANS",
  "📩 RECRUTEMENT ESPORT",
  "🔒 STAFF ESPORT",
  "🔒 STAFF ROCKET LEAGUE",
  "🔒 STAFF FORTNITE",
  "🔒 STAFF VALORANT",
  "🔒 STAFF CLASH OF CLANS"
]
# category, exact channel name, Discord channel type, requires private @everyone deny (0/1)
CHANNELS = [
  [
    "🏆 VEXORA ESPORTS",
    "📢・actualites-esport",
    "text",
    0
  ],
  [
    "🏆 VEXORA ESPORTS",
    "🏆・resultats-des-equipes",
    "text",
    0
  ],
  [
    "🏆 VEXORA ESPORTS",
    "👥・rosters",
    "text",
    0
  ],
  [
    "🏆 VEXORA ESPORTS",
    "📅・calendrier-esport",
    "text",
    0
  ],
  [
    "🏆 VEXORA ESPORTS",
    "🔴・matchs-en-direct",
    "text",
    0
  ],
  [
    "🏆 VEXORA ESPORTS",
    "🏅・palmares",
    "text",
    0
  ],
  [
    "🏆 VEXORA ESPORTS",
    "💬・discussion-esport",
    "text",
    0
  ],
  [
    "🚀 ROCKET LEAGUE",
    "👥・roster-rl",
    "text",
    0
  ],
  [
    "🚀 ROCKET LEAGUE",
    "💬・discussion-rl",
    "text",
    0
  ],
  [
    "🚀 ROCKET LEAGUE",
    "📢・actualites-rl",
    "text",
    0
  ],
  [
    "🚀 ROCKET LEAGUE",
    "📅・matchs-rl",
    "text",
    0
  ],
  [
    "🚀 ROCKET LEAGUE",
    "🏆・resultats-rl",
    "text",
    0
  ],
  [
    "🚀 ROCKET LEAGUE",
    "🔒・strategies-rl",
    "text",
    1
  ],
  [
    "🚀 ROCKET LEAGUE",
    "🔊・entrainement-rl",
    "voice",
    1
  ],
  [
    "🏗️ FORTNITE",
    "👥・roster-fn",
    "text",
    0
  ],
  [
    "🏗️ FORTNITE",
    "💬・discussion-fn",
    "text",
    0
  ],
  [
    "🏗️ FORTNITE",
    "📢・actualites-fn",
    "text",
    0
  ],
  [
    "🏗️ FORTNITE",
    "📅・matchs-fn",
    "text",
    0
  ],
  [
    "🏗️ FORTNITE",
    "🏆・resultats-fn",
    "text",
    0
  ],
  [
    "🏗️ FORTNITE",
    "🔒・strategies-fn",
    "text",
    1
  ],
  [
    "🏗️ FORTNITE",
    "🔊・entrainement-fn",
    "voice",
    1
  ],
  [
    "🎯 VALORANT",
    "👥・roster-valo",
    "text",
    0
  ],
  [
    "🎯 VALORANT",
    "💬・discussion-valo",
    "text",
    0
  ],
  [
    "🎯 VALORANT",
    "📢・actualites-valo",
    "text",
    0
  ],
  [
    "🎯 VALORANT",
    "📅・matchs-valo",
    "text",
    0
  ],
  [
    "🎯 VALORANT",
    "🏆・resultats-valo",
    "text",
    0
  ],
  [
    "🎯 VALORANT",
    "🔒・strategies-valo",
    "text",
    1
  ],
  [
    "🎯 VALORANT",
    "🔊・entrainement-valo",
    "voice",
    1
  ],
  [
    "⚔️ CLASH OF CLANS",
    "👥・roster-coc",
    "text",
    0
  ],
  [
    "⚔️ CLASH OF CLANS",
    "💬・discussion-coc",
    "text",
    0
  ],
  [
    "⚔️ CLASH OF CLANS",
    "📢・actualites-coc",
    "text",
    0
  ],
  [
    "⚔️ CLASH OF CLANS",
    "📅・matchs-coc",
    "text",
    0
  ],
  [
    "⚔️ CLASH OF CLANS",
    "🏆・resultats-coc",
    "text",
    0
  ],
  [
    "⚔️ CLASH OF CLANS",
    "🔒・strategies-coc",
    "text",
    1
  ],
  [
    "⚔️ CLASH OF CLANS",
    "🔊・entrainement-coc",
    "voice",
    1
  ],
  [
    "📩 RECRUTEMENT ESPORT",
    "📋・informations-recrutement",
    "text",
    0
  ],
  [
    "📩 RECRUTEMENT ESPORT",
    "🎟️・postuler-esport",
    "text",
    0
  ],
  [
    "🔒 STAFF ESPORT",
    "👑・direction-esport",
    "text",
    1
  ],
  [
    "🔒 STAFF ESPORT",
    "📋・gestion-esport",
    "text",
    1
  ],
  [
    "🔒 STAFF ESPORT",
    "👥・gestion-rosters",
    "text",
    1
  ],
  [
    "🔒 STAFF ESPORT",
    "📩・suivi-recrutement",
    "text",
    1
  ],
  [
    "🔒 STAFF ESPORT",
    "📅・planning-competitions",
    "text",
    1
  ],
  [
    "🔒 STAFF ESPORT",
    "🤝・partenariats-esport",
    "text",
    1
  ],
  [
    "🔒 STAFF ESPORT",
    "📢・communication-esport",
    "text",
    1
  ],
  [
    "🔒 STAFF ESPORT",
    "📊・performances-equipes",
    "text",
    1
  ],
  [
    "🔒 STAFF ROCKET LEAGUE",
    "📋・organisation",
    "text",
    1
  ],
  [
    "🔒 STAFF ROCKET LEAGUE",
    "📅・entrainements",
    "text",
    1
  ],
  [
    "🔒 STAFF ROCKET LEAGUE",
    "📊・analyses",
    "text",
    1
  ],
  [
    "🔒 STAFF ROCKET LEAGUE",
    "🎥・replays-vod",
    "text",
    1
  ],
  [
    "🔒 STAFF ROCKET LEAGUE",
    "💬・discussion-equipe",
    "text",
    1
  ],
  [
    "🔒 STAFF ROCKET LEAGUE",
    "🔊・vocal-equipe",
    "voice",
    1
  ],
  [
    "🔒 STAFF ROCKET LEAGUE",
    "🔊・vocal-coaching",
    "voice",
    1
  ],
  [
    "🔒 STAFF FORTNITE",
    "📋・organisation",
    "text",
    1
  ],
  [
    "🔒 STAFF FORTNITE",
    "📅・entrainements",
    "text",
    1
  ],
  [
    "🔒 STAFF FORTNITE",
    "📊・analyses",
    "text",
    1
  ],
  [
    "🔒 STAFF FORTNITE",
    "🎥・replays-vod",
    "text",
    1
  ],
  [
    "🔒 STAFF FORTNITE",
    "💬・discussion-equipe",
    "text",
    1
  ],
  [
    "🔒 STAFF FORTNITE",
    "🔊・vocal-equipe",
    "voice",
    1
  ],
  [
    "🔒 STAFF FORTNITE",
    "🔊・vocal-coaching",
    "voice",
    1
  ],
  [
    "🔒 STAFF VALORANT",
    "📋・organisation",
    "text",
    1
  ],
  [
    "🔒 STAFF VALORANT",
    "📅・entrainements",
    "text",
    1
  ],
  [
    "🔒 STAFF VALORANT",
    "📊・analyses",
    "text",
    1
  ],
  [
    "🔒 STAFF VALORANT",
    "🎥・replays-vod",
    "text",
    1
  ],
  [
    "🔒 STAFF VALORANT",
    "💬・discussion-equipe",
    "text",
    1
  ],
  [
    "🔒 STAFF VALORANT",
    "🔊・vocal-equipe",
    "voice",
    1
  ],
  [
    "🔒 STAFF VALORANT",
    "🔊・vocal-coaching",
    "voice",
    1
  ],
  [
    "🔒 STAFF CLASH OF CLANS",
    "📋・organisation",
    "text",
    1
  ],
  [
    "🔒 STAFF CLASH OF CLANS",
    "📅・entrainements",
    "text",
    1
  ],
  [
    "🔒 STAFF CLASH OF CLANS",
    "📊・analyses",
    "text",
    1
  ],
  [
    "🔒 STAFF CLASH OF CLANS",
    "🎥・replays-vod",
    "text",
    1
  ],
  [
    "🔒 STAFF CLASH OF CLANS",
    "💬・discussion-equipe",
    "text",
    1
  ],
  [
    "🔒 STAFF CLASH OF CLANS",
    "🔊・vocal-equipe",
    "voice",
    1
  ],
  [
    "🔒 STAFF CLASH OF CLANS",
    "🔊・vocal-coaching",
    "voice",
    1
  ]
]

assert (len(BASE_ROLES), len(EXTRA_ROLES), len(CATEGORIES), len(CHANNELS)) == (32, 13, 11, 73)
