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

```sh
# Envoyer une touche, trois secondes pour basculer sur la fenêtre visée
uv run -m controle_vocal.clavier --delai 3 droite
uv run -m controle_vocal.clavier --liste

# Relever l'identifiant des applications, pour remplir la colonne bundle_id
uv run -m controle_vocal.application --observer
```

## Profils

Un fichier par application dans `profils/`, six colonnes : `application`, `bundle_id`, `commande`, `touches`, `phrases`, `actif`. Les formulations acceptées se séparent par une barre verticale, les actions internes se préfixent par `@`.

```csv
application,bundle_id,commande,touches,phrases,actif
Canva,com.canva.CanvaDesktop,suivante,droite,suivante|suite|avance,oui
```

`_gabarit.csv` fournit les en-têtes seuls pour démarrer un nouveau profil, `defaut.csv` sert de repli sur les applications inconnues, limité à la navigation.

Une ligne dont la colonne `touches` est vide n'envoie rien : c'est ainsi qu'un raccourci non encore vérifié reste visible sans agir.

## Tests

```sh
uv run pytest
```
