"""Lecture des profils CSV, construction de la grammaire, résolution des phrases.

Un profil associe des formulations parlées à des combinaisons de touches, pour une
application donnée. Le format des colonnes est fixé dans SPECS.md.
"""

from __future__ import annotations

import csv
import unicodedata
from dataclasses import dataclass
from pathlib import Path

COLONNES = ("application", "bundle_id", "commande", "touches", "phrases", "actif")
SEPARATEUR_PHRASES = "|"
PREFIXE_ACTION_INTERNE = "@"

#: Jeton Vosk qui absorbe tout ce qui n'est pas dans la grammaire.
JETON_INCONNU = "[unk]"

#: Action réservée qui porte les formulations du mot de réveil, pas une commande.
ACTION_REVEIL = "@reveil"
MOT_REVEIL_PAR_DEFAUT = "higgins"

#: Actions internes garanties dans tout profil : elles ne dépendent d'aucune
#: application, et `@quitter` est le coupe-circuit du critère de succès n°4.
#: Un profil qui les omet se les voit ajoutées au chargement ; un profil qui les
#: déclare garde ses propres formulations.
ACTIONS_GARANTIES = {
    "@pause": ("pause", "silence"),
    "@reprise": ("reprise", "reprends"),
    "@quitter": ("extinction",),
}


class ErreurProfil(Exception):
    """Profil illisible ou incohérent : colonnes absentes, phrase en double."""


def normaliser(phrase: str) -> str:
    """Ramène une formulation à la forme que Vosk restitue : minuscules, espaces
    simples, sans ponctuation. Les accents sont conservés, le modèle français les rend."""
    sans_ponctuation = "".join(
        caractere
        for caractere in phrase.casefold()
        if not unicodedata.category(caractere).startswith("P")
    )
    return " ".join(sans_ponctuation.split())


@dataclass(frozen=True)
class Commande:
    """Une ligne du CSV : une action, ses formulations, la touche qu'elle envoie."""

    application: str
    bundle_id: str
    nom: str
    touches: str
    phrases: tuple[str, ...]
    actif: bool

    @property
    def est_action_interne(self) -> bool:
        return self.touches.startswith(PREFIXE_ACTION_INTERNE)

    @property
    def utilisable(self) -> bool:
        """Une commande active dont la touche reste à trouver n'envoie rien : on la
        traite comme inactive plutôt que d'envoyer une frappe vide."""
        return self.actif and bool(self.touches)


@dataclass(frozen=True)
class Profil:
    """Un fichier CSV chargé en mémoire, prêt à nourrir la grammaire et la décision."""

    nom: str
    chemin: Path
    commandes: tuple[Commande, ...]

    @property
    def application(self) -> str:
        for commande in self.commandes:
            if commande.application:
                return commande.application
        return self.nom

    @property
    def bundle_ids(self) -> frozenset[str]:
        return frozenset(c.bundle_id for c in self.commandes if c.bundle_id)

    @property
    def mots_reveil(self) -> tuple[str, ...]:
        """Formulations acceptées pour le mot de réveil. Le modèle français rend
        `Higgins` sous plusieurs graphies : la liste se complète à l'oreille."""
        for commande in self.commandes:
            if commande.touches == ACTION_REVEIL and commande.actif:
                return commande.phrases
        return (MOT_REVEIL_PAR_DEFAUT,)

    @property
    def commandes_utilisables(self) -> tuple[Commande, ...]:
        """Commandes qui peuvent réellement agir, mot de réveil exclu."""
        return tuple(
            c for c in self.commandes if c.utilisable and c.touches != ACTION_REVEIL
        )

    def phrases_acceptees(self) -> tuple[str, ...]:
        """Toutes les formulations de commande reconnues, dans l'ordre du fichier."""
        return tuple(
            phrase for c in self.commandes_utilisables for phrase in c.phrases
        )

    def resoudre(self, phrase: str) -> Commande | None:
        """Rend la commande correspondant à une formulation, ou rien si elle est
        inconnue, inactive ou sans touche."""
        cible = normaliser(phrase)
        for commande in self.commandes_utilisables:
            if cible in commande.phrases:
                return commande
        return None

    def grammaire(self) -> list[str]:
        """Grammaire fermée pour Vosk : les énoncés complets attendus, mot de réveil
        collé à la commande, plus le jeton qui absorbe le reste.

        Fournir les énoncés entiers plutôt que des mots isolés oriente le modèle vers
        le motif attendu ; la vérification stricte du motif reste faite à la décision.
        """
        enonces = [
            f"{reveil} {phrase}"
            for reveil in self.mots_reveil
            for phrase in self.phrases_acceptees()
        ]
        return sorted(dict.fromkeys(enonces)) + [JETON_INCONNU]


def _vrai_faux(valeur: str) -> bool:
    return valeur.strip().casefold() in {"oui", "o", "true", "1", "vrai"}


def charger(chemin: str | Path) -> Profil:
    """Charge un profil depuis son CSV. Le nom du profil est celui du fichier."""
    chemin = Path(chemin)
    try:
        texte = chemin.read_text(encoding="utf-8")
    except OSError as erreur:
        raise ErreurProfil(f"profil illisible : {chemin}") from erreur

    lecteur = csv.DictReader(texte.splitlines())
    manquantes = set(COLONNES) - set(lecteur.fieldnames or ())
    if manquantes:
        raise ErreurProfil(
            f"{chemin.name} : colonnes absentes {sorted(manquantes)}, "
            f"attendues {list(COLONNES)}"
        )

    commandes: list[Commande] = []
    deja_vues: dict[str, str] = {}
    for numero, ligne in enumerate(lecteur, start=2):
        nom = (ligne["commande"] or "").strip()
        if not nom:
            continue
        phrases = tuple(
            dict.fromkeys(
                normaliser(p)
                for p in (ligne["phrases"] or "").split(SEPARATEUR_PHRASES)
                if normaliser(p)
            )
        )
        commande = Commande(
            application=(ligne["application"] or "").strip(),
            bundle_id=(ligne["bundle_id"] or "").strip(),
            nom=nom,
            touches=(ligne["touches"] or "").strip(),
            phrases=phrases,
            actif=_vrai_faux(ligne["actif"] or ""),
        )
        if commande.utilisable:
            for phrase in phrases:
                if phrase in deja_vues:
                    raise ErreurProfil(
                        f"{chemin.name} ligne {numero} : la phrase « {phrase} » sert "
                        f"déjà à « {deja_vues[phrase]} », le choix serait imprévisible"
                    )
                deja_vues[phrase] = nom
        commandes.append(commande)

    return Profil(
        nom=chemin.stem,
        chemin=chemin,
        commandes=tuple(commandes) + _actions_manquantes(commandes),
    )


def _actions_manquantes(commandes: list[Commande]) -> tuple[Commande, ...]:
    """Complète un profil avec les actions internes qu'il n'a pas déclarées, pour
    qu'aucun profil ne perde la pause ni le coupe-circuit.

    Un fichier sans aucune commande n'est pas un profil mais un gabarit : il reste
    vierge.
    """
    if not commandes:
        return ()
    declarees = {c.touches for c in commandes}
    occupees = {p for c in commandes if c.utilisable for p in c.phrases}
    ajouts = []
    for action, phrases in ACTIONS_GARANTIES.items():
        if action in declarees:
            continue
        libres = tuple(p for p in phrases if p not in occupees)
        ajouts.append(
            Commande(
                application="",
                bundle_id="",
                nom=action.removeprefix(PREFIXE_ACTION_INTERNE),
                touches=action,
                phrases=libres,
                actif=bool(libres),
            )
        )
    return tuple(ajouts)


def charger_tous(dossier: str | Path) -> dict[str, Profil]:
    """Charge tous les profils d'un dossier, gabarit exclu (il n'a que ses en-têtes)."""
    dossier = Path(dossier)
    return {
        chemin.stem: charger(chemin)
        for chemin in sorted(dossier.glob("*.csv"))
        if not chemin.name.startswith("_")
    }


def profil_pour_bundle(
    profils: dict[str, Profil], bundle_id: str, repli: str = "defaut"
) -> Profil | None:
    """Choisit le profil de l'application au premier plan, avec repli sur `defaut`.

    Un profil dont le `bundle_id` n'est pas encore relevé n'est jamais détecté :
    il faut l'épingler au lancement.
    """
    for profil in profils.values():
        if bundle_id and bundle_id in profil.bundle_ids:
            return profil
    return profils.get(repli)
