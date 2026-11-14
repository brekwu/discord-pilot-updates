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

Le compteur démarre avec le nombre d'utilisations encore **visibles sur les
liens d'invitation Discord actifs**, puis augmente pour les arrivées attribuées
pendant que Discord Pilot est en ligne. Par exemple, un lien à dix utilisations
produit bien « onzième » lors de sa prochaine invitation identifiable. Discord
ne permet pas de reconstituer les liens supprimés, vanity ou les arrivées
manquées pendant que le bot est fermé : ce total peut donc être inférieur au
nombre historique réel. Quand l'invitant est ambigu, aucun compte n'est inventé.
Le maximum du compteur confirmé est conservé entre les redémarrages.

### Modules natifs locaux (v0.5.8)

L'onglet **Modules actifs** contient treize modules **réellement développés**,
désactivés au départ et configurés séparément pour chaque serveur :

1. Rôle attribué aux nouveaux membres.
2. XP, niveaux et classement (10 XP par message, délai de 60 secondes entre gains).
3. Anti-spam (6 messages en 8 secondes : suppression et pause de 60 secondes si la permission le permet).
4. Blocage des liens envoyés par les non-modérateurs.
5. Filtre de mots personnalisables (30 maximum).
6. Journal des messages édités/supprimés (auteur, salon, ID ; **pas** le contenu du message).
7. Réactions 👍 / 👎 automatiques dans un salon de suggestions.
8. Création/suppression de salons vocaux temporaires depuis un salon d'entrée.
9. Attribution et retrait d'un rôle par une réaction sur un message défini.
10. Message quotidien à heure fixe, selon l'heure française.
11. Tickets privés : panneau à bouton, un ticket ouvert par membre, salon réservé au demandeur et au rôle support sélectionné, fermeture et archivage sans suppression.
12. Modmail : un membre écrit au bot en message privé ; le bot vérifie son appartenance au serveur puis relaie au salon du support **privé**. Le staff répond avec `!reply ID_UTILISATEUR message` dans ce salon, uniquement après un message entrant récent du membre (30 jours maximum). Avec plusieurs serveurs disponibles, le membre précise `!mail ID_SERVEUR son message`. 15 secondes minimum entre deux messages transmis. L'activation exige **Message Content Intent** pour lire les commandes du staff.
13. Candidatures : publication d'un panneau à bouton, formulaire Discord avec pseudo, disponibilités et motivation, décision **Accepter/Refuser** réservée au rôle configuré ou aux gestionnaires de salons. Le candidat reçoit un MP seulement si ses paramètres de confidentialité l'autorisent. Le texte de candidature est envoyé au salon privé de validation, pas stocké dans l'historique local : seuls les statuts et identifiants sont conservés.

L'onglet Modules dispose aussi de deux types d'événements ponctuels :

- **Sondages** : 2 à 9 réponses, votes par réactions, durée de 1 minute à 7 jours et publication des résultats. Un utilisateur peut réagir à plusieurs réponses ; la version actuelle compte les réactions et n'impose pas un vote unique par personne.
- **Giveaways** : lancement dans un salon choisi, participation via 🎉, tirage aléatoire parmi les comptes non-bots ayant réagi et annonce du gagnant. Ce tirage est un outil d'animation, sans gestion juridique de concours ni remise automatique de lots.
- **Quiz** : 2 à 9 réponses sur des boutons Discord, une seule réponse par utilisateur, résultat et bonne réponse révélés à la fin. Aucune récompense automatique.

Les événements arrivent à échéance uniquement lorsque Discord Pilot est en marche ; s'il était fermé à l'heure prévue, les résultats sont calculés à sa prochaine connexion, à condition que le message et ses réactions soient toujours accessibles. Les tickets ouverts restent visibles dans Discord même si le bot est arrêté, mais leurs boutons ne fonctionneront qu'à son redémarrage. Le bot doit pouvoir **Gérer les salons**, **Voir les salons**, **Envoyer des messages**, **Lire l'historique** et **Ajouter des réactions**. Le panneau et les événements sont publiés seulement après une confirmation dans l'interface.

Les messages de bienvenue, départ et compteur d'invitation sont toujours
disponibles. Une demande explicite **« Active l'XP »**, **« Active l'antispam »**
ou **« Désactive l'antispam »** crée un plan validable depuis le studio.
Les autres modules s'activent depuis le tableau de bord, car ils exigent un
salon, un rôle, une réaction ou un texte précis.

**Pré-requis :** les salons/permissions doivent exister, le rôle du bot doit
être assez haut, et les événements ne se produisent que quand l'application
est ouverte et le bot en ligne. **Server Members Intent** est nécessaire aux
attributions à l'arrivée. **Message Content Intent** est nécessaire aux
filtres de liens/mots ; ce sont des autorisations privilégiées à activer dans
Discord Developer Portal > Bot. Le bot peut se connecter en mode limité si
Discord les refuse ; la configuration enregistrée ne constitue pas la preuve
qu'une intervention réelle a réussi.

L'anti-spam est un seuil simple, **pas** une protection anti-raid complète.
La réaction de rôle gère une association message/émoji/rôle par serveur pour
l'instant. Un bot local hors ligne ne peut pas publier les annonces manquées.

### Catalogue de 90 fonctionnalités et intégrations externes

L'onglet **Intégrations** permet de rechercher 90 idées par catégorie, de filtrer
les services externes et de préparer un lien vers le site officiel d'un éditeur.
Il répertorie notamment Jockie Music, Lyx, Wick, Carl-bot, Streamcord, sesh,
Ticket Tool, Xenon et Statbot. Les entrées sans intégration tierce vérifiée
sont explicitement indiquées **« Idée à développer »** : aucun bouton ne laisse
entendre qu'elles sont installées.

Tu peux aussi dicter ou taper « Mets de la musique », « Ajoute un système de
tickets et de sécurité anti-raid » ou « Installe un bot pour Twitch » : l'assistant
propose un **brouillon** d'intégration. Après validation, le résultat reste
**« Autorisation Discord requise »**, jamais « Terminé », tant que tu n'as pas
personnellement autorisé l'application tierce auprès de Discord. Les liens
pointent vers une liste fermée de domaines officiels, et aucune application
externe ne reçoit le token de Discord Pilot. Un bot ne peut pas autoriser une
autre application sur ton compte à ta place. L'ajout et la configuration
restent dépendants des permissions et capacités du fournisseur.

Le catalogue distingue désormais douze entrées correspondant à des fonctions
natifs, les fonctionnalités relevant de fournisseurs externes et les idées
encore non implémentées. **Il ne s'agit pas de 90 fonctionnalités terminées.**
Les bots tiers hébergés séparément peuvent continuer leurs tâches lorsque
Discord Pilot local est éteint.

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

Cette version configure les serveurs et exécute les dix modules locaux décrits
ci-dessus, plus les arrivées, départs et invitations. La musique et les bots
externes nécessitent toujours une autorisation distincte. Les **tickets privés
interactifs**, les flux Twitch/TikTok/YouTube, les tournois automatisés, les
jeux/music bots avec fournisseurs externes, l'anti-raid avancé et les autres
idées du catalogue ne sont pas réalisés par le moteur natif. Les modèles
« Support » créent des salons, **pas** un système de tickets interactifs complet.

Cette application ne nécessite pas et ne lit pas le code de ton bot existant. Pour fusionner plus tard les systèmes persistants dans le même programme, il faudra récupérer le dépôt source de ton bot.

## Tests locaux

```bash
python -m unittest discover -s tests -v
```

Le test d'application sans token Discord peut être lancé avec `DISCORD_PILOT_NO_BROWSER=1 python app.py` et le navigateur sur `http://127.0.0.1:8765`.
