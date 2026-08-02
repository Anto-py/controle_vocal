# controle_vocal

Télécommande vocale pour piloter une présentation projetée sur macOS, sans toucher au clavier. L'outil écoute le micro, reconnaît une commande précédée du mot de réveil `Higgins`, et envoie la combinaison de touches correspondante à l'application au premier plan.

La table qui associe les phrases aux touches est un simple CSV, un par application. Canva est le profil de référence, pas le seul.

Reconnaissance vocale **entièrement locale** : aucun son ne quitte la machine, aucun réseau à aucun étage.

Deux façons de s'en servir, selon ce qu'on vient y faire. Une **application macOS** autonome, qui s'installe d'un glisser-déposer et n'exige rien sur la machine d'accueil, pas même Python : voir « Installer sur un autre Mac ». Ou le **dépôt**, pour développer et pour tout ce que la ligne de commande permet de plus.

## Installation

```sh
uv sync
```

Le modèle de reconnaissance n'est pas versionné, il se télécharge une fois (environ 42 Mo) :

```sh
mkdir -p modeles
curl -L -o modeles/fr.zip https://alphacephei.com/vosk/models/vosk-model-small-fr-0.22.zip
unzip -q modeles/fr.zip -d modeles && rm modeles/fr.zip
```

**Autorisation macOS.** La simulation de frappes exige l'accès Accessibilité, à accorder une fois au terminal qui lance l'outil : Réglages système, Confidentialité et sécurité, Accessibilité. Sans elle, les touches partent dans le vide ; l'outil le détecte et le dit.

## Usage

Depuis le dossier du projet, sans quoi `uv` cherche un projet là où vous êtes et retombe sur le Python du système. Pour lancer d'ailleurs, ajouter `--directory <chemin du projet>` après `uv run`.

La télécommande se lance avant l'exposé. Sans option, le profil suit l'application au premier plan ; `--profil canva` l'épingle pour la séance, `--simulation` fait tout sauf envoyer les touches, `--pastille` ajoute la pastille d'état sur la projection.

```sh
uv run -m controle_vocal
uv run -m controle_vocal --profil canva
uv run -m controle_vocal --simulation
uv run -m controle_vocal --pastille
```

Les blocs de ce fichier ne portent aucun commentaire, et c'est délibéré : une apostrophe française collée après une commande peut ouvrir une chaîne dans zsh, qui reste alors bloqué au prompt `quote>` sans rien lancer.

Dites le mot de réveil, puis la commande, d'un seul tenant : « Higgins, suivante ». Le mot de réveil seul ne fait rien, la commande seule non plus. Trois commandes ne touchent pas à l'application : `pause` suspend l'écoute, `reprends` la rétablit, `extinction` arrête l'outil.

## Pastille d'état

`--pastille` pose un disque de couleur dans un coin de l'écran, visible par-dessus une présentation en plein écran. Sans texte : le public voit qu'une machine répond, sans lire le détail. Bleu, le mot de réveil a été entendu mais aucune commande ne suivait ; vert, la commande est partie ; orange, l'énoncé n'a pas atteint le seuil de certitude. Chacune s'allume une seconde et des poussières. Ce qui n'est pas adressé à l'outil n'allume rien.

Deux autres signaux ne s'éteignent pas : ils disent l'état de l'outil plutôt qu'une réponse à ce que vous venez de dire. Un disque violet pâle, allumé en permanence, l'outil écoute ; le même en demi-diamètre, l'écoute est en pause et seule la reprise sera entendue. Une commande les couvre le temps de sa couleur, puis ils reviennent. La pastille éteinte veut donc dire que l'outil est arrêté.

`--liste` donne les écrans et leur index, `--essai` fait défiler les couleurs le temps de basculer sur la présentation, veilleuses comprises. Le coin, l'écran, le diamètre et la durée d'allumage se règlent au lancement.

```sh
uv run -m controle_vocal.pastille --liste
uv run -m controle_vocal.pastille --essai --tours 10
uv run -m controle_vocal --pastille --pastille-coin haut_droite
uv run -m controle_vocal --pastille --pastille-ecran 1
uv run -m controle_vocal --pastille --pastille-taille 60 --pastille-duree 2
```

Si la pastille disparaît sous une application en plein écran, `--pastille-niveau bouclier` la fait passer au-dessus de tout, alertes système comprises.

Outils de mise au point, chacun lançable seul : envoyer une touche avec trois secondes pour basculer sur la fenêtre visée, relever l'identifiant d'une application pour remplir la colonne `bundle_id`, lister les micros, écouter ce qui est reconnu, ou afficher les décisions et leur motif sans envoyer la moindre touche.

```sh
uv run -m controle_vocal.clavier --delai 3 droite
uv run -m controle_vocal.clavier --liste
uv run -m controle_vocal.application --observer
uv run -m controle_vocal.audio --liste
uv run -m controle_vocal.reconnaissance
uv run -m controle_vocal.decision
uv run -m controle_vocal.decision --texte "higgins suivante" "pause reviens avance"
```

## Profils

Un fichier par application dans `profils/` (dans le dossier personnel quand l'outil tourne en application installée, voir plus bas), six colonnes : `application`, `bundle_id`, `commande`, `touches`, `phrases`, `actif`. Les formulations acceptées se séparent par une barre verticale.

```csv
application,bundle_id,commande,touches,phrases,actif
Canva,com.canva.CanvaDesktop,suivante,droite,suivante|suite|avance,oui
```

`_gabarit.csv` fournit les en-têtes seuls pour démarrer un nouveau profil, `defaut.csv` sert de repli sur les applications inconnues, limité à la navigation.

Une ligne dont la colonne `touches` est vide n'envoie rien : c'est ainsi qu'un raccourci non encore vérifié reste visible sans agir.

## Les mots de l'outil

Le mot de réveil, la pause, la reprise et l'extinction ne dépendent d'aucune application : ils se règlent une fois pour toutes, dans `profils/_actions.csv`, et la fenêtre de réglages leur donne quatre champs.

```csv
action,phrases,actif
@reveil,higgins,oui
@pause,pause|silence,oui
@reprise,reprise|reprends,oui
@quitter,extinction,oui
```

Trois choses à savoir avant de changer le mot de réveil.

Il doit appartenir au **vocabulaire du modèle français**. Vosk n'échoue pas sur un mot qu'il ignore : il l'écarte de la grammaire et se tait, si bien que la télécommande démarrerait sans jamais répondre. La fenêtre de réglages refuse donc d'écrire un mot inconnu, et la ligne de commande donne le même verdict :

```sh
uv run -m controle_vocal.reconnaissance --lexique bernadette zorglubtruc
```

Il doit rester **hors du vocabulaire d'un cours** : c'est la seule barrière contre les déclenchements involontaires, le seuil de certitude n'y suffisant pas. Un prénom peu courant fait l'affaire.

Enfin, le modèle rend parfois un même nom sous plusieurs graphies : la barre verticale les accueille toutes (`higgins|higuinsse`), et la liste se complète à l'oreille.

L'extinction et le mot de réveil ne se désactivent pas. Sans le premier, on s'enferme avec une télécommande qu'on n'arrête plus à la voix ; sans le second, la moindre phrase de cours agirait.

## Fenêtre de réglages

Une page web locale édite les profils et met l'outil en marche. Elle ne sert qu'à la boucle locale et ne parle à aucun réseau, polices comprises.

```sh
uv run -m controle_vocal.reglages
uv run -m controle_vocal.reglages --port 9000 --sans-navigateur
```

Le terminal n'est pas obligé : une application macOS fait la même chose d'un double-clic, et c'est la façon recommandée.

```sh
uv run outils/fabriquer_app.py
uv run outils/fabriquer_app.py --vers ~/Applications
```

La fabrication compile un petit lanceur en C et signe l'application, ce qui exige les outils en ligne de commande d'Xcode (`xcode-select --install`). Ce n'est pas du zèle : macOS n'accorde d'autorisation ni à un script, dont le processus réel est `/bin/bash`, ni à une application non signée, qu'il ne sait pas identifier.

L'autorisation Accessibilité s'accorde alors une fois à « Contrôle vocal », dans Réglages système, et cesse de dépendre du terminal ouvert ce jour-là. La page affiche en permanence si elle est accordée, et propose de la demander sinon. L'application n'est pas fournie, elle se fabrique. Sans option, elle reste **liée à ce dossier de projet**, ce qui est commode en développement, le code lancé étant celui qu'on vient d'éditer : la relancer suffit après une modification. Pour une application qui voyage, voir la section suivante.

Les réglages se ferment depuis la page, bouton « Fermer les réglages », qui arrête aussi la télécommande.

L'interrupteur en tête de page lance et arrête la télécommande, profil épinglé et pastille au choix. Il dit l'état réel plutôt que le dernier ordre reçu : un outil qui s'arrête seul, micro débranché ou « extinction » dite à la voix, y apparaît arrêté dans les deux secondes, avec les dernières lignes de sa sortie s'il a échoué. La télécommande ne survit pas à la fermeture des réglages.

Elle refuse d'écrire ce que le lancement refuserait : touche que le clavier ignore, action interne inventée, nom de commande en double, formulation qui sert déjà à une autre commande. Le refus dit la cause et la solution à côté du champ fautif, et le fichier reste intact. Le geste courant y est l'ajout d'une formulation ; les touches, elles, arrivent d'ordinaire par import d'un CSV rempli en amont.

Un profil enregistré est pris sans rien redémarrer, l'outil relisant ses profils à chaque changement d'application.

## Installer sur un autre Mac

`--autonome` embarque l'interpréteur Python, les paquets et le modèle de reconnaissance dans le bundle. L'application pèse alors environ 190 Mo et ne demande plus rien à la machine d'accueil : ni Python, ni `uv`, ni le dépôt, ni connexion. `--paquet` produit en plus une archive et la notice d'installation à joindre.

```sh
uv run outils/fabriquer_app.py --autonome
uv run outils/fabriquer_app.py --paquet ~/Desktop/livraison
uv run outils/fabriquer_app.py --paquet ~/Desktop/livraison --arch x86_64
```

Le lanceur est compilé pour les deux architectures, mais l'interpréteur embarqué n'en sert qu'une : `--arch` la choisit, et vaut par défaut celle de la machine qui fabrique. Un Mac Intel demande donc sa propre archive, fabricable depuis un Mac Apple Silicon.

**Chez le destinataire, trois gestes.** Glisser l'application dans Applications ; lever la mise en quarantaine ; ouvrir, puis accorder l'Accessibilité et le micro.

```sh
xattr -dr com.apple.quarantine "/Applications/Contrôle vocal.app"
```

Cette ligne est le péage d'une distribution de la main à la main. macOS marque tout fichier venu d'ailleurs, et refuse d'ouvrir une application qui n'est pas signée par un compte de développeur Apple, payant. Il annonce alors une application « endommagée », ce qu'elle n'est pas. Un certificat Developer ID et la notarisation supprimeraient cette étape ; ce projet ne les a pas.

**Où vont les profils.** L'application ne modifie jamais son propre contenu, sous peine d'invalider sa signature et l'autorisation qu'elle porte. Les CSV sont donc copiés au premier lancement dans le dossier personnel, et c'est là que l'interface les édite. Le chemin est rappelé sous la liste des profils.

```
~/Library/Application Support/Contrôle vocal/profils/
```

Une nouvelle version de l'application n'y touche pas : un profil déjà présent n'est jamais remplacé par celui d'origine. En contrepartie, un gabarit amélioré n'atteint pas qui a déjà le sien, et se récupère par le bouton d'import.

Une limite à connaître avant de distribuer : sans certificat, l'identité de l'application est le condensé de son binaire. Toute nouvelle version en change, et macOS redemande alors l'autorisation Accessibilité.

## Ce qui protège des déclenchements non voulus

Deux choses. D'abord le motif « mot de réveil, puis commande, et rien après » : la grammaire fermée du moteur ne rejette pas ce qu'elle ne connaît pas, elle y rabat le son, si bien qu'une phrase de cours ressort en commandes enchaînées. Ensuite le seuil (`--seuil`, 0,90 par défaut), qui porte sur le **mot le plus faible** de l'énoncé et non sur la moyenne : une moyenne laisserait un mot sûr racheter un mot douteux.

À la mesure, les commandes réelles sortent à 1,00 sur chaque mot, quand un mot de réveil fabriqué par le bruit ambiant tombe à 0,46. Les deux populations ne se recouvrent pas.

`--tolerance 1` admet un mot parasite entre le réveil et la commande, quand le moteur en glisse un. Cela rattrape des intentions claires, au prix d'une porte entrouverte au bruit ; la valeur par défaut, zéro, exige l'adjacence.

## Tests

```sh
uv run pytest
```
