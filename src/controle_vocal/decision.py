"""Du texte reconnu à l'action : motif de réveil, seuil, profil actif, états.

C'est l'étage qui décide de ne rien faire, ce qui est sa fonction principale. La
grammaire fermée ne rejette pas le hors-liste, elle y rabat le son : une phrase de
cours ressort en commandes enchaînées avec de bons scores. La première barrière est
donc le motif « mot de réveil puis commande, et rien après ».

La seconde barrière est le seuil, mais porté sur le **mot le plus faible** et non
sur la moyenne. Mesuré à la voix le 2026-08-02 : dix commandes réelles sortent à
1,00 sur chaque mot, un « higgins pause » fabriqué à partir d'une phrase de cours
passait à 0,82 de moyenne, et un mot rabattu tombe à 0,34. La moyenne laisse un mot
sûr racheter un mot douteux, le minimum ne le permet pas.

Le décideur n'envoie aucune touche : il rend une décision, l'appelant agit. Les
actions internes (pause, reprise, extinction) sont la seule chose qu'il tient
lui-même, parce qu'elles changent son propre état.

Essai à voix haute, sans qu'aucune touche ne parte :

    uv run -m controle_vocal.decision
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

from controle_vocal import application, profils
from controle_vocal.profils import Commande, Profil
from controle_vocal.reconnaissance import Enonce

#: Score minimal exigé du mot le plus faible d'un énoncé, mesuré à la voix le
#: 2026-08-02 : dix commandes réelles sortent toutes à 1,00 sur chaque mot, quand
#: un mot fabriqué à partir d'une phrase de cours tombe à 0,34. Le seuil laisse
#: donc de la marge à une prononciation moyenne tout en coupant le rabattement.
SEUIL_PAR_DEFAUT = 0.90

#: Mots parasites tolérés entre le mot de réveil et la commande. Zéro exige
#: l'adjacence stricte. À un, « higgins reprends noir » déclenche l'écran noir,
#: au prix d'une porte ouverte au bruit. Arbitrage à trancher sur mesures.
TOLERANCE_PAR_DEFAUT = 0

ACTION_PAUSE = "@pause"
ACTION_REPRISE = "@reprise"
ACTION_QUITTER = "@quitter"

NOM_PROFIL_REPLI = "defaut"


class ErreurDecision(Exception):
    """Jeu de profils inutilisable : repli absent, profil épinglé introuvable."""


class Etat(str, Enum):
    """Ce que le décideur a fait de l'énoncé, affiché tel quel dans le terminal."""

    IGNORE = "ignore"
    ENTENDU = "entendu"
    INCOMPRIS = "incompris"
    EXECUTE = "execute"


@dataclass(frozen=True)
class Decision:
    """Verdict rendu sur un énoncé : un état, une raison, parfois une commande."""

    etat: Etat
    raison: str
    enonce: Enonce | None = None
    commande: Commande | None = None
    profil: Profil | None = None

    @property
    def a_agir(self) -> bool:
        """Vrai quand il reste une combinaison de touches à envoyer.

        Les actions internes sont déjà appliquées par le décideur : l'appelant
        n'a rien à envoyer pour elles.
        """
        return (
            self.etat is Etat.EXECUTE
            and self.commande is not None
            and not self.commande.est_action_interne
        )

    @property
    def touches(self) -> str:
        return self.commande.touches if self.commande else ""

    def __str__(self) -> str:
        detail = f"[{self.etat.value}] {self.raison}"
        if self.enonce is not None and not self.enonce.vide:
            detail += (
                f"  ← « {self.enonce.texte} » (moyenne {self.enonce.certitude:.2f}, "
                f"plus faible {self.enonce.plancher:.2f})"
            )
        return detail


def _positions_reveil(mots: list[str], mots_reveil: tuple[str, ...]) -> list[int]:
    """Indices du mot qui suit chaque occurrence du mot de réveil.

    Une formulation de réveil peut compter plusieurs mots (« hé higgins ») : la
    comparaison porte donc sur des séquences, pas sur des mots isolés.
    """
    sequences = [reveil.split() for reveil in mots_reveil if reveil]
    fins: list[int] = []
    for depart in range(len(mots)):
        for sequence in sequences:
            arrivee = depart + len(sequence)
            if mots[depart:arrivee] == sequence:
                fins.append(arrivee)
    return fins


@dataclass(frozen=True)
class Motif:
    """Ce que la lecture d'un énoncé a trouvé : un réveil, parfois une commande."""

    reveil: bool
    commande: Commande | None
    raison: str


def reconnaitre_motif(
    texte: str,
    profil: Profil,
    tolerance: int = TOLERANCE_PAR_DEFAUT,
) -> Motif:
    """Cherche « mot de réveil puis commande » dans un énoncé reconnu.

    La commande doit terminer l'énoncé : ce qui traîne après elle est du bruit
    rabattu sur le vocabulaire, et suffit à tout rejeter.

    La dernière occurrence du mot de réveil l'emporte : « higgins euh higgins
    suivante » se lit comme une reprise, pas comme un échec.
    """
    mots = profils.normaliser(texte).split()
    fins_reveil = _positions_reveil(mots, profil.mots_reveil)
    if not fins_reveil:
        return Motif(reveil=False, commande=None, raison="pas de mot de réveil")

    for fin_reveil in reversed(fins_reveil):
        suite = mots[fin_reveil:]
        if not suite:
            continue
        for saute in range(min(tolerance, len(suite) - 1) + 1):
            commande = profil.resoudre(" ".join(suite[saute:]))
            if commande is not None:
                intercales = " ".join(suite[:saute])
                raison = f"commande « {commande.nom} »"
                if intercales:
                    raison += f", après le parasite « {intercales} »"
                return Motif(reveil=True, commande=commande, raison=raison)

    reste = " ".join(mots[fins_reveil[-1] :])
    raison = (
        f"aucune commande dans « {reste} »"
        if reste
        else "mot de réveil seul, sans commande"
    )
    return Motif(reveil=True, commande=None, raison=raison)


class Decideur:
    """Tient l'état de la séance : profil actif, écoute en pause, demande d'arrêt.

    La lecture de l'application au premier plan est injectable pour que les tests
    n'aient pas à basculer de fenêtre.
    """

    def __init__(
        self,
        jeu_de_profils: dict[str, Profil],
        epingle: str | None = None,
        seuil: float = SEUIL_PAR_DEFAUT,
        tolerance: int = TOLERANCE_PAR_DEFAUT,
        lire_application: Callable[[], application.ApplicationActive | None] | None = None,
    ) -> None:
        if not jeu_de_profils:
            raise ErreurDecision("aucun profil chargé")
        if epingle is not None and epingle not in jeu_de_profils:
            raise ErreurDecision(
                f"profil épinglé introuvable : « {epingle} », "
                f"connus {sorted(jeu_de_profils)}"
            )
        if NOM_PROFIL_REPLI not in jeu_de_profils and epingle is None:
            raise ErreurDecision(
                f"profil « {NOM_PROFIL_REPLI} » absent : sans lui, une application "
                "inconnue au premier plan laisserait la séance sans commande"
            )
        self._profils = jeu_de_profils
        self._epingle = epingle
        self.seuil = seuil
        self.tolerance = tolerance
        self._lire_application = lire_application or application.au_premier_plan
        self.en_pause = False
        self.arret_demande = False
        self._profil_courant = jeu_de_profils[epingle or NOM_PROFIL_REPLI]

    @property
    def profil_courant(self) -> Profil:
        """Dernier profil retenu, sans nouvelle interrogation du système."""
        return self._profil_courant

    @property
    def epingle(self) -> str | None:
        return self._epingle

    def rafraichir_profil(self) -> Profil:
        """Relit l'application au premier plan et met à jour le profil retenu.

        Un profil épinglé au lancement court-circuite la détection pour toute la
        séance : c'est le recours quand le `bundle_id` n'est pas encore relevé, ou
        quand l'application tourne dans un onglet de navigateur.
        """
        if self._epingle is None:
            active = self._lire_application()
            trouve = profils.profil_pour_bundle(
                self._profils, active.bundle_id if active else "", NOM_PROFIL_REPLI
            )
            if trouve is not None:
                self._profil_courant = trouve
        return self._profil_courant

    def traiter(self, enonce: Enonce | None) -> Decision:
        """Rend le verdict sur un énoncé reconnu, et applique les actions internes."""
        if enonce is None or enonce.vide:
            return Decision(Etat.IGNORE, "rien de reconnaissable", enonce)

        profil = self.rafraichir_profil()
        motif = reconnaitre_motif(enonce.texte, profil, self.tolerance)
        commande = motif.commande
        if commande is None:
            return Decision(
                Etat.ENTENDU if motif.reveil else Etat.IGNORE,
                motif.raison,
                enonce,
                profil=profil,
            )

        if enonce.plancher < self.seuil:
            return Decision(
                Etat.INCOMPRIS,
                f"{motif.raison}, mais le mot le plus faible sort à "
                f"{enonce.plancher:.2f}, sous le seuil {self.seuil:.2f}",
                enonce,
                commande,
                profil,
            )

        if self.en_pause and commande.touches != ACTION_REPRISE:
            return Decision(
                Etat.IGNORE,
                f"écoute en pause, seule la reprise est écoutée ({motif.raison})",
                enonce,
                profil=profil,
            )

        raison_finale = self._appliquer_action_interne(commande) or motif.raison
        return Decision(Etat.EXECUTE, raison_finale, enonce, commande, profil)

    def _appliquer_action_interne(self, commande: Commande) -> str | None:
        """Applique pause, reprise ou extinction, et rend la raison à afficher."""
        if commande.touches == ACTION_PAUSE:
            self.en_pause = True
            return "écoute en pause, dites la reprise pour reprendre"
        if commande.touches == ACTION_REPRISE:
            reprise = self.en_pause
            self.en_pause = False
            return "écoute reprise" if reprise else "écoute déjà active"
        if commande.touches == ACTION_QUITTER:
            self.arret_demande = True
            return "arrêt demandé"
        return None


def dossier_profils() -> Path:
    """Dossier des CSV, résolu depuis la racine du projet."""
    return Path(__file__).resolve().parents[2] / "profils"


def charger_jeu(dossier: str | Path | None = None) -> dict[str, Profil]:
    """Charge tous les profils, en traduisant l'erreur de lecture en erreur de décision."""
    try:
        return profils.charger_tous(dossier or dossier_profils())
    except profils.ErreurProfil as erreur:
        raise ErreurDecision(str(erreur)) from erreur


def _cli(arguments: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(
        prog="controle_vocal.decision",
        description="Écoute et affiche les décisions, sans envoyer aucune touche.",
    )
    analyseur.add_argument(
        "--profil", metavar="NOM", help="épingle un profil au lieu de le détecter"
    )
    analyseur.add_argument(
        "--seuil", type=float, default=SEUIL_PAR_DEFAUT, metavar="CERTITUDE"
    )
    analyseur.add_argument(
        "--tolerance",
        type=int,
        default=TOLERANCE_PAR_DEFAUT,
        metavar="MOTS",
        help="mots parasites admis entre le mot de réveil et la commande",
    )
    analyseur.add_argument(
        "--micro", metavar="INDEX_OU_NOM", help="périphérique d'entrée (voir --liste)"
    )
    analyseur.add_argument(
        "--detail",
        action="store_true",
        help="affiche le score de chaque mot, pour calibrer le seuil",
    )
    analyseur.add_argument(
        "--texte",
        nargs="*",
        metavar="ÉNONCÉ",
        help="juge des énoncés écrits au lieu d'écouter, pour éprouver le motif",
    )
    options = analyseur.parse_args(arguments)

    try:
        jeu = charger_jeu()
        decideur = Decideur(
            jeu,
            epingle=options.profil,
            seuil=options.seuil,
            tolerance=options.tolerance,
        )
    except ErreurDecision as erreur:
        print(f"Erreur : {erreur}", file=sys.stderr)
        return 2

    if options.texte:
        for texte in options.texte:
            faux = Enonce(texte=texte, certitude=1.0, mots=())
            print(decideur.traiter(faux))
        return 0

    from controle_vocal import audio
    from controle_vocal.reconnaissance import Reconnaisseur

    profil = decideur.rafraichir_profil()
    try:
        moteur = Reconnaisseur(profil.grammaire())
    except FileNotFoundError as erreur:
        print(f"Erreur : {erreur}", file=sys.stderr)
        return 2

    print(
        f"Écoute en cours, profil « {profil.nom} », seuil {options.seuil:.2f}, "
        f"tolérance {options.tolerance}. Ctrl+C pour arrêter.\n"
        "Aucune touche n'est envoyée : cet essai sert à mesurer les déclenchements."
    )
    compteurs: dict[Etat, int] = {etat: 0 for etat in Etat}
    try:
        with audio.Micro(taux=moteur.taux, peripherique=options.micro) as micro:
            for bloc in micro:
                enonce = moteur.alimenter(bloc)
                if enonce is None:
                    continue
                decision = decideur.traiter(enonce)
                compteurs[decision.etat] += 1
                if decision.etat is not Etat.IGNORE or not enonce.vide:
                    print(f"  {decision}")
                    if options.detail:
                        detail = "  ".join(
                            f"{mot} {score:.2f}" for mot, score in enonce.mots
                        )
                        print(f"      {detail}")
                if decideur.arret_demande:
                    break
    except audio.ErreurMicro as erreur:
        print(f"Erreur : {erreur}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        pass

    print(
        "\nBilan : "
        + ", ".join(f"{etat.value} {nombre}" for etat, nombre in compteurs.items())
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
