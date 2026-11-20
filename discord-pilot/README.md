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

## Nouveauté 0.5.19 : cahiers des charges jusqu'à 50 000 caractères

Dans **Admin Control Windows → Discord Pilot**, tu peux désormais coller une
demande de **50 000 caractères maximum**. Le compteur indique l'espace restant.
Les plans validés peuvent contenir jusqu'à **200 actions** ; une configuration
structurée en listes de rôles, catégories et salons est analysée sans Ollama.
Les demandes complexes sont découpées en sections pour les petits modèles
locaux, avec un contexte Discord ciblé et les consignes globales de
préservation du serveur transmises à chaque section. Une section d'action non
comprise bloque **l'ensemble** du brouillon ; les autres étapes ne partent pas
silencieusement sur le serveur.

Un brouillon peut créer des salons et rôles *déjà présents* : leur existence est
vérifiée au moment de l'exécution et ils sont ignorés si leur nom et leur
catégorie correspondent. Les permissions et automatisations ne sont jamais
devinées. Le modèle ne sait pas exécuter une opération Discord absente du
catalogue ; il demande alors de préciser ou de passer par un formulaire.

La préparation **n'applique aucune modification Discord** : relis le serveur,
les permissions et les actions puis confirme. Les tickets interactifs et
les automatisations locales ne répondent que lorsque Discord Pilot est lancé
et que le bot est connecté. Les tests automatiques valident la préparation et
les refus de demandes incomplètes, pas toutes les formulations du langage.

## Nouveauté 0.5.18 : préparateur de demandes

Le studio comprend maintenant la demande naturelle « Modifie les rôles pour les
salons au revoir, bienvenue, invitation pour pas que tout le monde puisse écrire
dedans », même sans modèle IA. Il prépare trois actions de **lecture seule**
avant toute exécution Discord. Les salons restent visibles, les membres ordinaires
perdent les droits d'écriture de ces salons (y compris les autorisations particulières
de leurs rôles), et les administrateurs et ce bot conservent leurs droits. Les
intégrations tierces avec un rôle géré ou des permissions individuelles explicites
conservent leurs autorisations : vérifier leurs messages après application.

L'interface affiche maintenant **Demande comprise** avec une reformulation
du plan. Les noms de salons comportant des accents, emojis, tirets ou un simple
pluriel sont rapprochés seulement si le résultat est unique. Sinon, l'application
demande le nom exact. **Aucune modification n'est faite avant validation.**

Cette version est distribuée avec le bouton **MAJ** : il n'est pas nécessaire de
réinstaller Discord Pilot ni de coller un token déjà mémorisé.

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

### Gestion guidée des rôles et des salons (v0.5.11)

La phrase **« Gère les rôles des salons que tu viens de créer »** ouvre désormais la configuration de permissions : Discord Pilot recherche les salons textuels ou vocaux de la **dernière création réellement réussie** dans l'historique du serveur connecté. Un bouton **Gérer les rôles et accès des salons** permet aussi d'ouvrir cet écran directement.

Choisis le rôle, un salon précis ou les derniers salons créés, puis pour chaque permission : **autoriser, refuser, ne pas modifier, revenir à l'héritage**. Seules la visibilité et l'écriture (ou la connexion aux vocaux) sont modifiables par cet outil. Un brouillon à valider est créé avant toute action Discord. Le rôle `@everyone` peut être sélectionné explicitement : autoriser sa visibilité peut exposer un salon privé, donc vérifie soigneusement le plan. Le bot doit disposer de **Gérer les rôles** et du droit de modifier les salons concernés.

### Demandes que l'IA ne sait pas convertir (v0.5.12)

Si le modèle Ollama retourne une liste vide, pose une question ou renvoie un format inexploitable après une tentative de réparation, Discord Pilot **n'invente aucune action**. Il affiche une fenêtre pour reformuler la demande, en conservant la phrase originale et en donnant des exemples d'actions prises en charge. L'utilisateur peut la modifier puis relancer la préparation. Une demande générale sur les accès des salons ouvre directement le sélecteur de permissions. Aucune action Discord ne part sans un brouillon valide puis une confirmation explicite.

### P1 — Compréhension des consignes (v0.5.13)

Le planificateur peut désormais combiner plusieurs commandes connues, par exemple « Crée un salon annonces et active les statistiques des messages », en un seul brouillon ordonné. Une sous-demande inconnue empêche la préparation automatique d'un plan partiel. Les actions restent strictement limitées aux capacités autorisées.

Avec Ollama, Discord Pilot utilise un format de réponse JSON Schema lorsque la version locale le permet, puis revient au mode JSON simple si nécessaire. Il fournit au modèle une photographie bornée des salons, catégories et rôles du serveur connecté, ainsi que les dernières opérations enregistrées. Ce contexte permet de mieux comprendre les références comme « le dernier salon créé », sans garantir leur interprétation par tous les modèles. Aucune exécution Discord n'est accordée directement au modèle.

Si une précision est nécessaire, la fenêtre garde la demande d'origine et propose un second champ pour répondre à la question. Cette réponse est conservée avec la demande pour la génération suivante. Les commandes incompatibles ou ambiguës restent non exécutées.

Si aucune création de salon n'est enregistrée comme réussie, tu peux choisir les salons existants individuellement. Les permissions ne peuvent pas être choisies automatiquement sans connaître les règles d'accès souhaitées.

### P2 — Permissions ciblées, modules et enchaînement (v0.5.14)

Le planificateur accepte `set_role_access` pour modifier **uniquement** la visibilité et l'écriture ou la connexion d'un rôle précis dans un salon précis, par nom ou ID. Il reconnaît aussi localement des demandes explicites comme « Autorise le rôle Membre à voir le salon annonces ». Les demandes floues restent dirigées vers le sélecteur de permissions. Un modèle n'a pas le droit d'inventer des changements de permissions à partir d'une simple demande de rangement.

L'action `configure_module` permet de préparer les paramètres des **17 modules natifs** avec un nom de salon/rôle ou un ID Discord. Les paramètres sont vérifiés selon le formulaire réel de chaque module : un salon privé requis doit être effectivement privé, un ID doit exister sur le serveur, et une information manquante interdit l'activation. Les objets créés plus tôt dans le même plan peuvent être réutilisés immédiatement, même avant la mise à jour du cache Discord.

Les étapes d'un plan sont exécutées **dans l'ordre**. En cas d'échec, les suivantes sont marquées « Non exécuté » pour éviter une configuration incomplète. Les opérations idempotentes de permissions et de renommage peuvent être retentées **une seule fois** sur des erreurs HTTP transitoires ; jamais les suppressions, publications ou créations. Toutes les actions restent soumises à la confirmation du brouillon. Un modèle local Ollama doit être installé pour interpréter les configurations complexes qui ne correspondent pas aux commandes hors ligne reconnues.

### P3 — Panneaux interactifs de tickets et candidatures (v0.5.15)

Les actions `publish_ticket_panel` et `publish_application_panel` publient les panneaux Discord fonctionnels après configuration des modules correspondants. Exemple sans modèle IA : « Publie le panneau des tickets » crée un brouillon à confirmer. Lorsque le modèle prépare l'**activation** de tickets ou candidatures, Discord Pilot ajoute la publication correspondante au plan si elle était demandée, sans publier en arrière-plan. Une demande « sans publier » conserve la configuration sans panneau.

Les boutons utilisent les gestionnaires natifs existants : création/archivage de tickets privés et soumission/validation de candidatures. Avant d'envoyer un panneau, le bot vérifie que le module est activé, que ses salons et rôles existent et que le salon de validation des candidatures est privé. Il recherche aussi un panneau déjà publié. Si ce message existe, aucune copie n'est envoyée ; s'il a réellement été supprimé, il peut être recréé. Si sa présence ne peut être vérifiée, l'opération échoue au lieu de produire des doublons.

La recette automatisée teste la chaîne « créer catégorie et rôle → créer salon → configurer tickets → publier le panneau », les interactions simulées et le vrai exécutable Windows **hors connexion Discord**. Un test de bout en bout sur un serveur Discord réel et sur le modèle Ollama de ton PC reste indispensable ; aucun serveur réel n'a été modifié par cette recette.

### P4 — Demandes complètes et diagnostic Discord connecté (v0.5.17)

Sans Ollama, le Studio sait maintenant préparer un **plan unique** à partir de certaines demandes composées : créer une catégorie, ses salons et rôles, rendre le salon de validation privé, activer les tickets ou candidatures et publier le panneau interactif. Les ressources nécessaires doivent être nommées dans la demande. Exemple : « Crée une catégorie SUPPORT et un salon tickets dans la catégorie SUPPORT et un rôle Support puis active les tickets et publie le panneau des tickets ». Le modèle de serveur **communauté, tournoi, entreprise ou support** peut aussi être demandé en français. Les modules sans paramètres XP, anti-spam, anti-liens et statistiques peuvent être activés ensemble dans une instruction explicite.

Les plans ne sont jamais exécutés sans validation. Une instruction ambiguë ou mêlant des demandes non prises en charge ne doit pas entraîner un **plan partiel silencieux**. Ces scénarios vérifiés ne signifient pas que tout Discord soit configurable en langage libre : le moteur reste limité aux actions du catalogue autorisé, et des formulaires sont requis lorsqu'il manque des informations. Exemple candidatures : « Crée une catégorie RECRUTEMENT et un salon candidatures dans la catégorie RECRUTEMENT et un salon validation dans la catégorie RECRUTEMENT et un rôle RH puis rends le salon validation privé pour le rôle RH puis active les candidatures ».

Le bouton **Tester le bot sur Discord**, dans le Studio, fonctionne après connexion du bot local. Le mode lecture seule utilise les appels API de Discord pour récupérer les salons et rôles, puis vérifie les permissions globales. Sur autorisation explicite, le mode actif crée un **salon privé temporaire**, y écrit un message, relit ce message et supprime ce seul salon. En cas d'échec de nettoyage, l'interface indique précisément le nom et l'ID du salon laissé sur le serveur. Le diagnostic ne peut pas être lancé depuis une instance déconnectée ; une simulation de ces appels dans les tests n'est **pas** une validation d'un serveur réel.

### Modules natifs locaux (v0.5.11)

**Correction v0.5.10 du planificateur IA :** accepte désormais certaines réponses JSON courantes d'Ollama (`plan`, `commands`, `result`, ou une action unique) tout en appliquant exactement la même liste d'actions autorisées. « Active les statistiques des messages » peut être traité localement sans dépendre d'Ollama. Si le modèle ne peut toujours pas produire un plan, l'application explique les opérations possibles et propose l'onglet Modules actifs pour les fonctions nécessitant des paramètres ; elle n'invente pas une action à exécuter.

L'onglet **Modules actifs** contient dix-sept modules **réellement développés**,
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
14. Récompense de niveau : rôle automatique lorsqu'un membre atteint un niveau configuré (1 à 1 000). Il faut activer séparément XP et placer le rôle du bot au-dessus du rôle à attribuer. Les niveaux déjà atteints sont vérifiés lors du prochain message XP du membre.
15. Récompense d'invitations : rôle attribué à l'invitant après un seuil de 1 à 1 000 arrivées attribuables. **Server Members Intent** et l'autorisation **Gérer le serveur** sont requis. Le suivi n'est pas exhaustif : Discord ne permet pas toujours d'attribuer une arrivée ni de retrouver les invitations expirées.
16. Statistiques d'activité : compte les messages vus pendant que le bot tourne, sans stocker leur contenu. Le classement est affiché dans l'interface Windows.
17. Avertissements manuels : formulaire d'administration locale réservé à l'interface de ton PC ; vérifie que l'ID correspond à un membre et journalise le motif dans un salon **privé**. L'historique récent (500 entrées maximum) et les totaux sont conservés localement. **Aucune sanction, aucun MP et aucun timeout automatiques**.

L'interface montre également le classement des invitations identifiées, y compris si aucune récompense n'est activée. Il s'agit de nombres partiels et non d'un audit exhaustif des invitations historiques.

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

Cette version configure les serveurs et exécute les dix-sept modules locaux
décrits ci-dessus, plus les arrivées, départs et invitations. La musique et les
bots externes nécessitent toujours une autorisation distincte. Les flux
Twitch/TikTok/YouTube, les tournois automatisés, les jeux/music bots avec
fournisseurs externes, l'anti-raid avancé et les autres idées du catalogue non
marquées « natives » ne sont pas réalisés par le moteur local. Les tickets
interactifs sont disponibles via le module spécifique, pas uniquement en créant
les salons d'un modèle « Support ».

Cette application ne nécessite pas et ne lit pas le code de ton bot existant. Pour fusionner plus tard les systèmes persistants dans le même programme, il faudra récupérer le dépôt source de ton bot.

## Tests locaux

```bash
python -m unittest discover -s tests -v
```

Le test d'application sans token Discord peut être lancé avec `DISCORD_PILOT_NO_BROWSER=1 python app.py` et le navigateur sur `http://127.0.0.1:8765`.
