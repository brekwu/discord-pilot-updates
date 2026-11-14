# Discord Pilot — studio de configuration Discord local

Application personnelle Windows 11 pour organiser et modifier les serveurs auxquels ton bot Discord a accès. L'interface s'ouvre dans ton navigateur, mais tourne **uniquement sur ton PC** (`127.0.0.1:8765`). Elle ne publie pas de site en ligne.

## Démarrer sous Windows : un seul fichier

**Télécharge `DiscordPilot.exe` depuis la dernière version GitHub, puis double-clique dessus.**
L'application inclut Python, les dépendances et son interface ; aucun autre fichier
n'est nécessaire pour démarrer. Le premier lancement peut demander quelques
secondes, le temps d'extraire le programme. Une page s'ouvre sur
`http://127.0.0.1:8765` ; elle fonctionne uniquement sur ton ordinateur.
Si ce port est occupé par une ancienne instance, Discord Pilot essaie
automatiquement `8766` à `8770`, puis un port local libre. Le navigateur ouvre
l'adresse réellement utilisée, sans intervention de ta part.

Le bouton **MAJ** de l'exécutable télécharge et installe les futures versions
Windows, vérifie leur SHA-256, conserve une sauvegarde de l'ancien programme,
puis redémarre l'application. Tes données restent dans
`%LOCALAPPDATA%\DiscordPilot\`. Si Windows bloque la mise à jour,
le diagnostic se trouve dans `%LOCALAPPDATA%\DiscordPilot\updater.log`.

### Variante pour développeurs (fichiers Python)

1. Décompresse le ZIP dans un dossier de ton choix.
2. Installe **Python 3.10 ou plus récent**, si tu ne l'as pas déjà (option « Add Python to PATH » recommandée).
3. Double-clique sur **`DEMARRER_DISCORD_PILOT.cmd`** dans le dossier extrait. L'ancien `LANCER_DISCORD_PILOT.bat` pointe désormais vers ce même lanceur. Le premier lancement installe deux bibliothèques Python gratuites et nécessite Internet.
4. Une page s'ouvre : `http://127.0.0.1:8765`.
5. Clique sur **Mon bot Discord** en bas à gauche. Colle le token du bot, pas ton mot de passe Discord. Tu le récupères dans [Discord Developer Portal](https://discord.com/developers/applications) → ton application → **Bot**. Si tu ne l'as pas sauvegardé lors de sa création, Discord ne permet pas de le revoir : **Reset Token** en crée un nouveau et invalide l'ancien. Dans ce cas, il faudra aussi remplacer le token dans le code ou l'hébergement de ton bot déjà en service.
6. Une fois connecté, tous les serveurs où se trouve ce bot apparaissent automatiquement. Sélectionne un serveur, saisis ta demande puis clique **Préparer le plan**, vérifie et **Appliquer sur Discord**.

## Le bouton « MAJ » : fonctionnement

La version **0.4.1** intègre un bouton **MAJ** (en haut de l'interface) :

1. **Vérifier** la dernière version à partir d'un manifeste sur GitHub.
2. **Télécharger** le programme Windows `.exe` (ou le ZIP pour l'ancienne installation)
   via HTTPS avec vérification SHA-256.
3. **Installer et redémarrer** avec le mécanisme de mise à jour adapté :
   exécutable autonome ou ancien lanceur Windows `.cmd`.
4. Conserver les paramètres, le token chiffré, les historiques et une **sauvegarde des fichiers remplacés**.

Il sait aussi **importer un ZIP de mise à jour localement** sans configurer de source distante.

La source de publication est [le manifeste GitHub officiel](https://raw.githubusercontent.com/brekwu/discord-pilot-updates/main/update.json). Le bouton **MAJ** utilise **automatiquement** cette source. Les futures versions devront toujours être publiées dans ce dépôt pour être détectées. Le dépôt contenant le bot principal reste privé et séparé.

Exemple de manifeste pour une **prochaine** version (valeurs fictives) :

```json
{
  "version": "0.4.2",
  "url": "https://github.com/COMPTE/DiscordPilot/releases/download/v0.4.2/DiscordPilot_Windows.zip",
  "sha256": "REMPLACER_PAR_64_CARACTERES_HEXADECIMAUX",
  "exe_url": "https://github.com/COMPTE/DiscordPilot/releases/download/v0.4.2/DiscordPilot.exe",
  "exe_sha256": "REMPLACER_PAR_64_CARACTERES_HEXADECIMAUX"
}
```

La source est déjà enregistrée par défaut. Il n'est pas nécessaire de coller une URL dans l'interface. Les mises à jour suivantes pourront être récupérées depuis l'application sans retélécharger manuellement le programme, tant qu'elles seront publiées sur GitHub et que le lanceur Windows fonctionnera correctement.

**Il faut télécharger l'exécutable une première fois ; les prochaines mises à jour s'installent depuis l'application.**

**Important :** connaître l'identifiant d'un serveur ne suffit pas. Le bot doit y être invité avec les autorisations adaptées ; le bouton **Inviter mon bot** génère son lien d'invitation, sans demander la permission Administrateur.

### Exemples sans IA

- `Crée une catégorie ACCUEIL avec les salons bienvenue, reglement et annonces`
- `Crée les rôles Membre, Modérateur et VIP`
- `Crée un salon vocal Général dans la catégorie COMMUNAUTÉ`
- `Crée la catégorie SUPPORT ; crée les salons tickets et entraide dans la catégorie SUPPORT`
- `Renomme le salon general en discussion`
- `Rends le salon staff privé pour le rôle Modérateur`
- `Envoie "Le tournoi commence samedi à 14h" dans #annonces`
- `Je veux un salon au-revoir et invitation, et des messages de bienvenue à chaque arrivée, de départ et un compteur pour chaque personne invitée`

### Bienvenue, au-revoir et compteur d'invitations

Discord Pilot propose maintenant trois actions de configuration :
`configure_welcome`, `configure_farewell`, `configure_invites`. Les salons nécessaires
sont créés seulement lorsqu'ils ont été demandés ; les salons existants sont
réutilisés. Le plan est toujours à approuver avant application.

Ces messages fonctionnent **uniquement quand le bot Discord Pilot est lancé et
connecté**. Comme il s'agit d'un bot local, il n'envoie pas de messages durant
les périodes où l'application est fermée. Il n'y a pas d'hébergement ajouté.

Pour recevoir les arrivées et départs, l'option **Server Members Intent** doit
être activée dans Discord Developer Portal > application > Bot. Sans cette
autorisation Discord obligatoire, l'application reste utilisable pour les
autres opérations, mais les messages d'événements sont en attente.

Pour attribuer une invitation, le bot doit aussi avoir la permission
**Gérer le serveur** (lecture des invitations), ainsi que **Voir le salon** et
**Envoyer des messages** dans les salons ciblés. Le bouton « Inviter mon bot »
demande ces permissions sans demander Administrateur. Pour un bot déjà invité,
accorde les autorisations via les rôles Discord.

Le compteur commence aux invitations **attribuées pendant que Discord Pilot est
en ligne**. Discord ne garantit pas l'identification de l'invitant pour les
liens vanity, les invitations retirées ou plusieurs arrivées simultanées.
Dans ces cas, aucun compte n'est inventé. Le compteur validé est conservé
entre les redémarrages de l'application.

Sépare plusieurs instructions distinctes par un **point-virgule**. Le moteur sans IA couvre une liste volontairement limitée d'opérations ; si une demande est trop complexe, il refuse au lieu d'exécuter une partie silencieusement.

### Demandes plus libres : IA locale gratuite

Pour des consignes plus complexes, installe [Ollama](https://ollama.com/) sur ton PC et télécharge un modèle, par exemple dans PowerShell :

```powershell
ollama pull qwen2.5:7b
```

Démarre Ollama. Discord Pilot détecte les modèles installés automatiquement. Choisis le mode automatique ou « IA locale Ollama ». **Il n'y a pas de coût d'API** : le modèle tourne localement sur ta machine (avec la RTX 4080 Super, un modèle 7B quantifié est adapté).

Le modèle ne peut proposer que des actions validées par l'application : création de catégories, salons texte/vocaux, rôles sans permissions spéciales, renommage, description, message, salon privé pour un rôle, automatisations d'arrivée/départ/invitations et suppression explicite. Les commandes arbitraires et les scripts générés ne sont pas exécutés.

### Sécurité et historique

- Les plans sont présentés avant application. Les suppressions demandent, en plus, le nom exact du serveur.
- Le bot utilise uniquement ses propres droits Discord et respecte les autorisations de Discord ; ses accès ne peuvent pas être contournés.
- Les demandes sont enregistrées **par identifiant de serveur** avec leur résultat étape par étape. Export JSON disponible depuis l'onglet Historique.
- Sous Windows, la case « Mémoriser » chiffre le token du bot avec **DPAPI**, lié au compte Windows de l'utilisateur. Le token n'est jamais renvoyé à la page Web ni inscrit dans l'historique.
- Les données de l'application sont stockées dans `%LOCALAPPDATA%\DiscordPilot\` (elles ne disparaissent pas lorsque tu déplaces le dossier de l'application).
- L'application doit rester ouverte pour piloter le bot. Elle ne remplace pas une éventuelle exécution 24h/24 de ton bot existant ni ses fonctionnalités propres.
- En cas de problème de lancement, la fenêtre noire **reste ouverte** et affiche l'erreur. Un diagnostic est enregistré dans `%LOCALAPPDATA%\DiscordPilot\launcher.log`.

### Générer soi-même un exécutable Windows

Le dépôt de mise à jour publie un `.exe` compilé sous Windows. Si tu souhaites le
recompiler toi-même, installe PyInstaller puis exécute le script de construction
sur Windows. Le ZIP source reste disponible pour diagnostic et développement.

### Limitations actuelles

Cette version configure les serveurs et propose trois automatismes simples **tant que le bot local est en ligne** : arrivées, départs et invitations. Elle ne programme pas encore les autres comportements permanents (tickets interactifs, onboarding avec boutons, flux réseaux, modération automatique, etc.), qui demandent une logique d'exécution persistante. Les modèles « Support » créent donc des salons de support, **pas un système complet de tickets interactifs**.

Cette application ne nécessite pas et ne lit pas le code de ton bot existant. Pour fusionner plus tard les systèmes persistants dans le même programme, il faudra récupérer le dépôt source de ton bot.

## Tests locaux

```bash
python -m unittest discover -s tests -v
```

Le test d'application sans token Discord peut être lancé avec `DISCORD_PILOT_NO_BROWSER=1 python app.py` et le navigateur sur `http://127.0.0.1:8765`.
