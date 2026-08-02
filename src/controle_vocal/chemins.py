"""Où l'outil lit, où il écrit. Source unique, parce que la réponse change.

Le programme tourne dans deux mondes qui ne se ressemblent pas :

- **depuis le dépôt** (`uv run -m controle_vocal`), tout vit côte à côte, les
  modèles et les profils sont deux dossiers de la racine, et l'utilisateur édite
  les CSV du dépôt ;
- **depuis une application installée**, le code et les modèles sont enfermés dans
  un bundle qu'on ne doit **jamais** écrire. Une app qui modifie son propre
  contenu invalide sa signature, et macOS finit par refuser de l'ouvrir. Les
  profils partent donc dans le dossier de données de l'utilisateur.

Trois fonctions suffisent à dire lequel des deux mondes on habite, et une variable
d'environnement permet de forcer la main dans les deux cas :

    CONTROLE_VOCAL_RESSOURCES   dossier livré, lu et jamais écrit (modèles, gabarits)
    CONTROLE_VOCAL_PROFILS      dossier des CSV, écrit par l'interface de réglages

Le lanceur de l'application pose la première ; les tests posent l'une ou l'autre.
Sans elles, la détection se fait toute seule, sur le chemin de ce fichier.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

#: Nom du dossier de données, tel qu'il apparaîtra dans la bibliothèque de
#: l'utilisateur. Avec accent et espace : ce dossier se montre, il ne s'écrit pas
#: en ligne de commande.
NOM_APPLICATION = "Contrôle vocal"

VARIABLE_RESSOURCES = "CONTROLE_VOCAL_RESSOURCES"
VARIABLE_PROFILS = "CONTROLE_VOCAL_PROFILS"

DOSSIER_MODELES = "modeles"
DOSSIER_PROFILS = "profils"


def _variable(nom: str) -> Path | None:
    """Lit une surcharge d'environnement. Une variable vide vaut absente : une
    coquille dans un script ne doit pas envoyer l'outil écrire à la racine."""
    valeur = (os.environ.get(nom) or "").strip()
    return Path(valeur).expanduser() if valeur else None


def bundle(depuis: str | Path | None = None) -> Path | None:
    """Le `.app` dont ce code fait partie, ou rien si on tourne depuis le dépôt.

    On remonte les dossiers parents jusqu'au premier qui porte le suffixe `.app`.
    Se demander au lieu de se faire dire : le Python embarqué peut être lancé à la
    main, hors du lanceur qui pose les variables d'environnement, et il doit alors
    se comporter pareil.
    """
    depart = Path(depuis) if depuis is not None else Path(__file__)
    for parent in depart.resolve().parents:
        if parent.suffix == ".app":
            return parent
    return None


def racine_projet() -> Path:
    """Racine du dépôt, deux dossiers au-dessus du paquet."""
    return Path(__file__).resolve().parents[2]


def dossier_ressources() -> Path:
    """Ce qui est livré et jamais modifié : modèles Vosk, profils d'origine."""
    if force := _variable(VARIABLE_RESSOURCES):
        return force
    if app := bundle():
        return app / "Contents" / "Resources"
    return racine_projet()


def dossier_donnees() -> Path:
    """Dossier personnel de l'utilisateur, hors du bundle et hors du dépôt."""
    return Path.home() / "Library" / "Application Support" / NOM_APPLICATION


def dossier_modeles() -> Path:
    return dossier_ressources() / DOSSIER_MODELES


def dossier_profils(amorcer: bool = True) -> Path:
    """Dossier des CSV, le seul que l'outil écrive.

    Depuis le dépôt, c'est `profils/` : le développement continue de lire et
    d'écrire les fichiers versionnés. Depuis une application, c'est le dossier de
    données, garni au premier lancement des profils livrés (`amorcer`).
    """
    if force := _variable(VARIABLE_PROFILS):
        return force
    if bundle() is None:
        return racine_projet() / DOSSIER_PROFILS

    cible = dossier_donnees() / DOSSIER_PROFILS
    if amorcer:
        amorcer_profils(dossier_ressources() / DOSSIER_PROFILS, cible)
    return cible


def amorcer_profils(source: str | Path, cible: str | Path) -> list[str]:
    """Copie dans `cible` les CSV livrés qui n'y sont pas encore, et rend leurs noms.

    Jamais d'écrasement : un profil que l'utilisateur a corrigé lui appartient, et
    une mise à jour de l'application n'a pas à défaire son travail. Le prix de ce
    choix est qu'un gabarit amélioré n'atteint pas celui qui a déjà le sien ; c'est
    le moindre des deux maux, l'autre étant de perdre en silence des réglages
    éprouvés en séance.
    """
    source, cible = Path(source), Path(cible)
    if not source.is_dir():
        return []

    cible.mkdir(parents=True, exist_ok=True)
    copies = []
    for fichier in sorted(source.glob("*.csv")):
        destination = cible / fichier.name
        if destination.exists():
            continue
        shutil.copyfile(fichier, destination)
        copies.append(fichier.name)
    return copies
