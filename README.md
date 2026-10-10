# Lohyx Hub

Un launcher Minecraft Java moderne, écrit en Python.

**Télécharger :** https://venonlohan5-hue.github.io/lohyx

## Fonctions

- Profils Vanilla, Fabric et Forge, avec la mémoire réglable pour chacun
- Mods, shaders et packs de ressources depuis Modrinth, avec leurs dépendances
- Boost FPS : installe des mods de performance en un clic (profils Fabric)
- Test de puissance du PC : le bouton Jouer est vert, jaune, orange ou rouge selon le profil
- Liste de serveurs avec joueurs en ligne et ping, et bouton « Rejoindre »
- Skins, actualités Minecraft, sauvegarde des mondes, journal du jeu
- Connexion Microsoft optionnelle (mode hors-ligne par défaut)
- Mises à jour automatiques, avec vérification de l'empreinte (sha256) du fichier

## Utiliser le code source

Il faut Python 3.10 ou plus récent.

    pip install minecraft-launcher-lib
    python LohyxHub.pyw

## Fabriquer le .exe soi-même

    pip install pyinstaller minecraft-launcher-lib
    python -m PyInstaller --noconsole --onefile --name LohyxHub --icon lohyx_icone.ico LohyxHub.pyw

Le fichier se trouve ensuite dans `dist/LohyxHub.exe`. Les versions publiées ici sont
construites automatiquement par GitHub Actions (voir `.github/workflows/build.yml`),
à partir du code source de ce dépôt.

## Confidentialité

Lohyx Hub n'envoie aucune statistique et n'a pas de compte utilisateur. Ses données
(profils, réglages, jeu) restent sur ton PC, dans le dossier `.lohyx` de ton profil Windows.

Il se connecte à internet uniquement pour ce que tu demandes :

- `api.modrinth.com` : recherche et téléchargement de mods, shaders et packs
- les serveurs Mojang et Microsoft : téléchargement de Minecraft, de Java, et connexion au compte
- `launchercontent.mojang.com` : actualités Minecraft
- `mc-heads.net` : affichage des skins (le pseudo cherché lui est transmis)
- le site de mises à jour (`venonlohan5-hue.github.io`) : savoir si une nouvelle version existe

Le jeton de connexion Microsoft, s'il est utilisé, n'est jamais envoyé ailleurs que chez Microsoft et Mojang.

## Signature du code

Le `.exe` n'est pas encore signé. Windows peut donc afficher « Éditeur inconnu » :
clique sur « Informations complémentaires », puis « Exécuter quand même ».
Une demande de signature gratuite pour projet open source est en préparation.

## Licence

MIT, voir le fichier `LICENSE`.

Lohyx Hub est un projet indépendant. Il n'est pas affilié à Mojang, Microsoft ou Modrinth.
Minecraft est une marque de Mojang Studios.
