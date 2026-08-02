# controle_vocal

Télécommande vocale pour piloter une présentation projetée sur macOS, sans toucher au clavier. L'outil écoute le micro, reconnaît une commande précédée du mot de réveil `Higgins`, et envoie la combinaison de touches correspondante à l'application au premier plan.

La table qui associe les phrases aux touches est un simple CSV, un par application. Canva est le profil de référence, pas le seul.

Reconnaissance vocale **entièrement locale** : aucun son ne quitte la machine, aucun réseau à aucun étage.

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

`--pastille` pose un disque de couleur dans un coin de l'écran, visible par-dessus une présentation en plein écran. Sans texte : le public voit qu'une machine répond, sans lire le détail. Bleu, le mot de réveil a été entendu mais aucune commande ne suivait ; vert, la commande est partie ; orange, l'énoncé n'a pas atteint le seuil de certitude. Ce qui n'est pas adressé à l'outil n'allume rien.

`--liste` donne les écrans et leur index, `--essai` fait défiler les trois couleurs le temps de basculer sur la présentation. Le coin, l'écran, le diamètre et la durée d'allumage se règlent au lancement.

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

Un fichier par application dans `profils/`, six colonnes : `application`, `bundle_id`, `commande`, `touches`, `phrases`, `actif`. Les formulations acceptées se séparent par une barre verticale, les actions internes se préfixent par `@`.

```csv
application,bundle_id,commande,touches,phrases,actif
Canva,com.canva.CanvaDesktop,suivante,droite,suivante|suite|avance,oui
```

`_gabarit.csv` fournit les en-têtes seuls pour démarrer un nouveau profil, `defaut.csv` sert de repli sur les applications inconnues, limité à la navigation.

Une ligne dont la colonne `touches` est vide n'envoie rien : c'est ainsi qu'un raccourci non encore vérifié reste visible sans agir.

## Ce qui protège des déclenchements non voulus

Deux choses. D'abord le motif « mot de réveil, puis commande, et rien après » : la grammaire fermée du moteur ne rejette pas ce qu'elle ne connaît pas, elle y rabat le son, si bien qu'une phrase de cours ressort en commandes enchaînées. Ensuite le seuil (`--seuil`, 0,90 par défaut), qui porte sur le **mot le plus faible** de l'énoncé et non sur la moyenne : une moyenne laisserait un mot sûr racheter un mot douteux.

À la mesure, les commandes réelles sortent à 1,00 sur chaque mot, quand un mot de réveil fabriqué par le bruit ambiant tombe à 0,46. Les deux populations ne se recouvrent pas.

`--tolerance 1` admet un mot parasite entre le réveil et la commande, quand le moteur en glisse un. Cela rattrape des intentions claires, au prix d'une porte entrouverte au bruit ; la valeur par défaut, zéro, exige l'adjacence.

## Tests

```sh
uv run pytest
```
