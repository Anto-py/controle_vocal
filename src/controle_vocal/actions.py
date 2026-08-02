"""Les actions internes de l'outil : mot de réveil, pause, reprise, extinction.

Ces quatre-là ne dépendent d'aucune application. Elles règlent l'outil, pas Canva.
Elles vivent donc dans un fichier à part, `_actions.csv`, au lieu d'être recopiées
dans chaque profil : changer le mot de réveil demandait sinon de passer sur tous
les fichiers, et un profil oublié gardait l'ancien mot en pleine séance.

Le préfixe `_` du nom l'exclut de la liste des profils, règle déjà en place pour
le gabarit. Trois colonnes seulement :

    action,phrases,actif
    @reveil,higgins,oui

Deux actions ne se désactivent pas, et c'est délibéré. `@quitter` est le
coupe-circuit : sans lui, on s'enferme avec une télécommande qu'on n'arrête plus
à la voix. `@reveil` est la seule barrière contre les faux déclenchements, la
grammaire fermée rabattant le hors-liste sur le vocabulaire au lieu de le rejeter.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from controle_vocal import tableaux
from controle_vocal.tableaux import Refus

COLONNES = ("action", "phrases", "actif")

#: Nom du fichier dans le dossier des profils. Le `_` l'en exclut la liste.
FICHIER = "_actions.csv"

ACTION_REVEIL = "@reveil"
ACTION_PAUSE = "@pause"
ACTION_REPRISE = "@reprise"
ACTION_QUITTER = "@quitter"

#: Formulations d'origine, et ordre d'affichage. Une action absente du fichier
#: retombe ici plutôt que de disparaître : aucun réglage ne peut priver l'outil
#: de sa pause ni de son coupe-circuit.
DEFAUTS: dict[str, tuple[str, ...]] = {
    ACTION_REVEIL: ("higgins",),
    ACTION_PAUSE: ("pause", "silence"),
    ACTION_REPRISE: ("reprise", "reprends"),
    ACTION_QUITTER: ("extinction",),
}

RESERVEES = frozenset(DEFAUTS)

#: Actions dont l'interrupteur est fixé : voir l'en-tête du module.
TOUJOURS_ACTIVES = frozenset({ACTION_REVEIL, ACTION_QUITTER})

#: Ce que l'interface écrit à côté de chaque champ. Ici plutôt que dans la page :
#: le serveur les sert avec les valeurs, et une action ajoutée un jour n'oblige
#: pas à retoucher le JavaScript.
LIBELLES: dict[str, tuple[str, str]] = {
    ACTION_REVEIL: (
        "Mot de réveil",
        "Se dit avant chaque commande. Un mot que le modèle français connaît, "
        "et qu'on ne prononce pas en cours.",
    ),
    ACTION_PAUSE: ("Mettre en pause", "L'outil cesse d'agir jusqu'à la reprise."),
    ACTION_REPRISE: ("Reprendre", "Seule commande écoutée pendant la pause."),
    ACTION_QUITTER: ("Arrêter l'outil", "Coupe-circuit : ne se désactive pas."),
}


class ErreurActions(tableaux.ErreurTableau):
    """Fichier d'actions illisible ou mal formé."""


@dataclass(frozen=True)
class Action:
    """Une action interne et les formulations qui la déclenchent."""

    nom: str
    phrases: tuple[str, ...]
    actif: bool

    @property
    def utilisable(self) -> bool:
        """Une action active mais sans formulation ne peut pas être dite."""
        return self.actif and bool(self.phrases)


@dataclass(frozen=True)
class Jeu:
    """Les quatre actions internes, complètes et dans l'ordre fixé."""

    actions: tuple[Action, ...]

    def action(self, nom: str) -> Action:
        for action in self.actions:
            if action.nom == nom:
                return action
        raise KeyError(nom)

    @property
    def mots_reveil(self) -> tuple[str, ...]:
        """Formulations acceptées pour le mot de réveil. Le modèle rend un même
        nom sous plusieurs graphies : la liste se complète à l'oreille."""
        reveil = self.action(ACTION_REVEIL)
        return reveil.phrases or DEFAUTS[ACTION_REVEIL]

    @property
    def utilisables(self) -> tuple[Action, ...]:
        """Actions déclenchables, mot de réveil exclu : il n'en est pas une, il
        précède les autres."""
        return tuple(
            a for a in self.actions if a.utilisable and a.nom != ACTION_REVEIL
        )

    def phrases_prises(self) -> dict[str, str]:
        """Formulation normalisée vers l'action qui la porte, mot de réveil compris.

        Sert à refuser dans un profil une commande qui reprendrait une de ces
        formulations : « higgins higgins » ou une pause qui vaut aussi diapositive
        suivante rendraient le choix imprévisible.
        """
        prises: dict[str, str] = {}
        for action in self.actions:
            if not action.utilisable and action.nom != ACTION_REVEIL:
                continue
            for phrase in action.phrases:
                prises.setdefault(phrase, action.nom)
        return prises


def defauts() -> list[dict[str, str]]:
    """Le fichier d'origine, sous forme de lignes brutes."""
    return [
        {
            "action": nom,
            "phrases": tableaux.joindre_phrases(phrases),
            "actif": "oui",
        }
        for nom, phrases in DEFAUTS.items()
    ]


def chemin(dossier: str | Path) -> Path:
    return Path(dossier) / FICHIER


def lire_lignes(chemin_fichier: str | Path) -> list[dict[str, str]]:
    """Rend les lignes du fichier telles qu'elles sont écrites, ou les défauts s'il
    n'existe pas : l'interface a toujours quatre champs à montrer."""
    chemin_fichier = Path(chemin_fichier)
    if not chemin_fichier.exists():
        return defauts()
    try:
        lignes = tableaux.lire_lignes(chemin_fichier, COLONNES)
    except tableaux.ErreurTableau as erreur:
        raise ErreurActions(str(erreur)) from erreur
    return _completer(lignes)


def _completer(lignes: list[dict[str, str]]) -> list[dict[str, str]]:
    """Ajoute les actions que le fichier ne déclare pas, dans l'ordre de `DEFAUTS`."""
    declarees = {(ligne.get("action") or "").strip() for ligne in lignes}
    manquantes = [
        ligne for ligne in defauts() if ligne["action"] not in declarees
    ]
    return lignes + manquantes


def charger(chemin_fichier: str | Path | None = None) -> Jeu:
    """Charge le jeu d'actions. Sans fichier, les valeurs d'origine."""
    lignes = defauts() if chemin_fichier is None else lire_lignes(chemin_fichier)
    par_nom = {ligne["action"].strip(): ligne for ligne in lignes}
    actions = []
    for nom in DEFAUTS:
        ligne = par_nom.get(nom, {})
        phrases = tableaux.decouper_phrases(ligne.get("phrases", ""))
        actif = tableaux.vrai_faux(ligne.get("actif", "oui"))
        actions.append(
            Action(
                nom=nom,
                phrases=phrases or DEFAUTS[nom],
                actif=actif or nom in TOUJOURS_ACTIVES,
            )
        )
    return Jeu(actions=tuple(actions))


def valider(
    lignes: Iterable[Mapping[str, str]],
    phrases_reservees: Mapping[str, str] | None = None,
) -> list[Refus]:
    """Rejoue les refus que le chargement et le lancement opposeraient.

    `phrases_reservees` associe une formulation déjà prise à ce qui la porte,
    typiquement les commandes des profils : une action qui reprendrait « suivante »
    rendrait le choix imprévisible.
    """
    refus: list[Refus] = []
    prises: dict[str, str] = dict(phrases_reservees or {})
    vues: dict[str, int] = {}

    for numero, ligne in enumerate(lignes, start=2):
        if manquantes := set(COLONNES) - set(ligne):
            refus.append(Refus(numero, "", f"colonnes absentes : {sorted(manquantes)}"))
            continue

        nom = ligne["action"].strip()
        if nom not in RESERVEES:
            refus.append(
                Refus(
                    numero,
                    "action",
                    f"action inconnue : « {nom or 'vide'} », "
                    f"attendues {sorted(RESERVEES)}",
                )
            )
            continue
        if nom in vues:
            refus.append(
                Refus(
                    numero,
                    "action",
                    f"« {nom} » est déjà réglée ligne {vues[nom]} : "
                    "la seconde resterait sans effet",
                )
            )
            continue
        vues[nom] = numero

        actif = tableaux.vrai_faux(ligne["actif"]) or nom in TOUJOURS_ACTIVES
        phrases = tableaux.decouper_phrases(ligne["phrases"])

        if not phrases and nom in TOUJOURS_ACTIVES:
            refus.append(
                Refus(
                    numero,
                    "phrases",
                    f"« {nom} » ne peut pas rester sans formulation : "
                    + (
                        "sans mot de réveil, la moindre phrase de cours agirait"
                        if nom == ACTION_REVEIL
                        else "c'est le seul moyen d'arrêter l'outil à la voix"
                    ),
                )
            )
        elif not phrases and actif:
            refus.append(
                Refus(
                    numero,
                    "phrases",
                    f"« {nom} » est active mais n'a aucune formulation : "
                    "en donner une, ou la désactiver",
                )
            )

        if not actif:
            continue
        for phrase in phrases:
            if phrase in prises:
                refus.append(
                    Refus(
                        numero,
                        "phrases",
                        f"« {phrase} » sert déjà à « {prises[phrase]} » : "
                        "le choix serait imprévisible, en changer une",
                    )
                )
            else:
                prises[phrase] = nom

    return refus


def ecrire(chemin_fichier: str | Path, lignes: Iterable[Mapping[str, str]]) -> None:
    """Écrit le fichier d'actions, colonnes dans l'ordre fixé."""
    tableaux.ecrire(chemin_fichier, lignes, COLONNES)
