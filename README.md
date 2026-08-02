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

```sh
# La télécommande, à lancer avant l'exposé
uv run -m controle_vocal
uv run -m controle_vocal --profil canva     # profil épinglé pour la séance
uv run -m controle_vocal --simulation       # tout sauf l'envoi des touches
```

Dites le mot de réveil, puis la commande, d'un seul tenant : « Higgins, suivante ». Le mot de réveil seul ne fait rien, la commande seule non plus. Trois commandes ne touchent pas à l'application : `pause` suspend l'écoute, `reprends` la rétablit, `extinction` arrête l'outil.

Outils de mise au point, chacun lançable seul :

```sh
# Envoyer une touche, trois secondes pour basculer sur la fenêtre visée
uv run -m controle_vocal.clavier --delai 3 droite
uv run -m controle_vocal.clavier --liste

# Relever l'identifiant des applications, pour remplir la colonne bundle_id
uv run -m controle_vocal.application --observer

# Micros disponibles, puis écoute qui affiche ce qui est reconnu, sans rien exécuter
uv run -m controle_vocal.audio --liste
uv run -m controle_vocal.reconnaissance

# Écoute qui affiche les décisions et leur motif, sans envoyer de touche
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
