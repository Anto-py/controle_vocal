"""Lecture et écriture des CSV de réglage, sans rien savoir de leur contenu.

Deux fichiers passent par ici, et ils n'ont ni les mêmes colonnes ni le même rôle :
les profils d'application (`profils.py`) et les actions internes communes à tous
les profils (`actions.py`). Ce module tient ce qu'ils partagent, la forme des
formulations et l'écriture sans perte, pour qu'aucun des deux n'ait à importer
l'autre.

Il tient aussi le découpage d'une cellule de formulations, qui était écrit deux
fois dans `profils.py`, au chargement et à la validation. Ces deux-là doivent
rendre exactement le même verdict, sans quoi l'interface accepte un fichier qui
fera échouer un lancement : le partage n'est pas une commodité, c'est la garantie.
"""

from __future__ import annotations

import csv
import io
import os
import tempfile
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

#: Sépare les formulations d'une même ligne : « pause|silence ».
SEPARATEUR_PHRASES = "|"

#: Valeurs lues comme un oui dans une colonne `actif`.
VRAI = frozenset({"oui", "o", "true", "1", "vrai"})


class ErreurTableau(Exception):
    """CSV illisible ou mal formé : fichier absent, colonnes manquantes."""


@dataclass(frozen=True)
class Refus:
    """Une raison de ne pas écrire un fichier, située dedans.

    `ligne` suit la numérotation du fichier, en-tête compris : la première ligne de
    données porte le numéro 2. Zéro désigne le fichier entier.
    """

    ligne: int
    colonne: str
    message: str


def normaliser(phrase: str) -> str:
    """Ramène une formulation à la forme que Vosk restitue : minuscules, espaces
    simples, sans ponctuation. Les accents sont conservés, le modèle français les rend."""
    sans_ponctuation = "".join(
        caractere
        for caractere in phrase.casefold()
        if not unicodedata.category(caractere).startswith("P")
    )
    return " ".join(sans_ponctuation.split())


def vrai_faux(valeur: str) -> bool:
    return valeur.strip().casefold() in VRAI


def decouper_phrases(cellule: str) -> tuple[str, ...]:
    """Découpe une cellule de formulations, normalise, dédoublonne, garde l'ordre."""
    return tuple(
        dict.fromkeys(
            normalisee
            for morceau in (cellule or "").split(SEPARATEUR_PHRASES)
            if (normalisee := normaliser(morceau))
        )
    )


def joindre_phrases(phrases: Iterable[str]) -> str:
    """Écrit des formulations dans une cellule, pour reposer un fichier lu."""
    return SEPARATEUR_PHRASES.join(phrases)


def lire_lignes(chemin: str | Path, colonnes: Sequence[str]) -> list[dict[str, str]]:
    """Rend les lignes d'un CSV telles qu'elles sont écrites, colonnes attendues comblées."""
    chemin = Path(chemin)
    try:
        texte = chemin.read_text(encoding="utf-8")
    except OSError as erreur:
        raise ErreurTableau(f"fichier illisible : {chemin}") from erreur

    lecteur = csv.DictReader(texte.splitlines())
    if manquantes := set(colonnes) - set(lecteur.fieldnames or ()):
        raise ErreurTableau(
            f"{chemin.name} : colonnes absentes {sorted(manquantes)}, "
            f"attendues {list(colonnes)}"
        )
    return [
        {colonne: (ligne.get(colonne) or "") for colonne in colonnes} for ligne in lecteur
    ]


def rendre_csv(lignes: Iterable[Mapping[str, str]], colonnes: Sequence[str]) -> str:
    """Sérialise des lignes, colonnes dans l'ordre fixé."""
    tampon = io.StringIO()
    redacteur = csv.DictWriter(
        tampon, fieldnames=list(colonnes), lineterminator="\n", extrasaction="ignore"
    )
    redacteur.writeheader()
    for ligne in lignes:
        redacteur.writerow({colonne: ligne.get(colonne, "") for colonne in colonnes})
    return tampon.getvalue()


def ecrire(
    chemin: str | Path, lignes: Iterable[Mapping[str, str]], colonnes: Sequence[str]
) -> None:
    """Écrit un CSV, par fichier temporaire puis renommage.

    Une écriture interrompue laisserait sinon un fichier tronqué, découvert au
    lancement suivant, c'est-à-dire au pire moment.
    """
    chemin = Path(chemin)
    contenu = rendre_csv(lignes, colonnes)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    descripteur, provisoire = tempfile.mkstemp(
        dir=chemin.parent, prefix=f".{chemin.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descripteur, "w", encoding="utf-8", newline="") as fichier:
            fichier.write(contenu)
            fichier.flush()
            os.fsync(fichier.fileno())
        os.replace(provisoire, chemin)
    except BaseException:
        Path(provisoire).unlink(missing_ok=True)
        raise
