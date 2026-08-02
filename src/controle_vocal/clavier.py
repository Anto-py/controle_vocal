"""Envoi de combinaisons de touches à l'application au premier plan, par CGEvent.

Les codes de touches macOS sont **positionnels** : ils désignent un emplacement du
clavier, pas un caractère. La table ci-dessous suit la disposition ANSI. Les touches
qui changent de place en AZERTY (`a`, `q`, `z`, `w`, `m`) enverraient donc la lettre
de la position QWERTY correspondante. Sans effet sur le profil Canva, qui n'emploie
que les flèches, `Échap` et `cmd+alt+p` (le `p` est au même endroit dans les deux
dispositions). À reprendre le jour où un profil aura besoin d'une de ces lettres.

Essai en ligne de commande, trois secondes pour basculer sur la fenêtre visée :

    uv run -m controle_vocal.clavier --delai 3 droite
"""

from __future__ import annotations

import argparse
import sys
import time

from ApplicationServices import (
    AXIsProcessTrusted,
    AXIsProcessTrustedWithOptions,
    kAXTrustedCheckOptionPrompt,
)
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventPost,
    CGEventSetFlags,
    CGEventSourceCreate,
    kCGEventFlagMaskAlternate,
    kCGEventFlagMaskCommand,
    kCGEventFlagMaskControl,
    kCGEventFlagMaskShift,
    kCGEventSourceStateHIDSystemState,
    kCGHIDEventTap,
)

SEPARATEUR_COMBINAISON = "+"

#: Délai entre l'appui et le relâchement : sans lui, une application web peut
#: manquer l'événement.
DELAI_APPUI = 0.01

MODIFICATEURS: dict[str, int] = {
    "cmd": kCGEventFlagMaskCommand,
    "commande": kCGEventFlagMaskCommand,
    "alt": kCGEventFlagMaskAlternate,
    "option": kCGEventFlagMaskAlternate,
    "ctrl": kCGEventFlagMaskControl,
    "controle": kCGEventFlagMaskControl,
    "maj": kCGEventFlagMaskShift,
    "shift": kCGEventFlagMaskShift,
}

TOUCHES: dict[str, int] = {
    # Navigation
    "gauche": 0x7B,
    "droite": 0x7C,
    "bas": 0x7D,
    "haut": 0x7E,
    "debut": 0x73,
    "fin": 0x77,
    "page_haut": 0x74,
    "page_bas": 0x79,
    # Édition et validation
    "echap": 0x35,
    "entree": 0x24,
    "espace": 0x31,
    "tab": 0x30,
    "retour_arriere": 0x33,
    "suppr": 0x75,
    # Chiffres de la rangée du haut
    "0": 0x1D,
    "1": 0x12,
    "2": 0x13,
    "3": 0x14,
    "4": 0x15,
    "5": 0x17,
    "6": 0x16,
    "7": 0x1A,
    "8": 0x1C,
    "9": 0x19,
    # Lettres, par position ANSI (voir l'avertissement en tête de module)
    "a": 0x00,
    "b": 0x0B,
    "c": 0x08,
    "d": 0x02,
    "e": 0x0E,
    "f": 0x03,
    "g": 0x05,
    "h": 0x04,
    "i": 0x22,
    "j": 0x26,
    "k": 0x28,
    "l": 0x25,
    "m": 0x2E,
    "n": 0x2D,
    "o": 0x1F,
    "p": 0x23,
    "q": 0x0C,
    "r": 0x0F,
    "s": 0x01,
    "t": 0x11,
    "u": 0x20,
    "v": 0x09,
    "w": 0x0D,
    "x": 0x07,
    "y": 0x10,
    "z": 0x06,
    # Fonctions
    "f1": 0x7A,
    "f2": 0x78,
    "f3": 0x63,
    "f4": 0x76,
    "f5": 0x60,
    "f6": 0x61,
    "f7": 0x62,
    "f8": 0x64,
    "f9": 0x65,
    "f10": 0x6D,
    "f11": 0x67,
    "f12": 0x6F,
}


class ErreurTouche(Exception):
    """Combinaison invalide : touche inconnue, modificateur seul, forme vide."""


def analyser(combinaison: str) -> tuple[int, int]:
    """Traduit `cmd+alt+p` en un code de touche et un masque de modificateurs."""
    morceaux = [m.strip().casefold() for m in combinaison.split(SEPARATEUR_COMBINAISON)]
    morceaux = [m for m in morceaux if m]
    if not morceaux:
        raise ErreurTouche("combinaison vide")

    *prefixes, finale = morceaux
    flags = 0
    for prefixe in prefixes:
        if prefixe not in MODIFICATEURS:
            raise ErreurTouche(
                f"modificateur inconnu : « {prefixe} », "
                f"attendus {sorted(set(MODIFICATEURS))}"
            )
        flags |= MODIFICATEURS[prefixe]

    if finale in MODIFICATEURS and finale not in TOUCHES:
        raise ErreurTouche(f"« {combinaison} » n'a pas de touche après le modificateur")
    if finale not in TOUCHES:
        raise ErreurTouche(f"touche inconnue : « {finale} »")
    return TOUCHES[finale], flags


def accessibilite_accordee() -> bool:
    """Sans cette autorisation, les frappes partent dans le vide sans erreur.

    Constate, sans demander : à appeler autant qu'on veut, y compris en boucle.
    """
    return bool(AXIsProcessTrusted())


def demander_accessibilite() -> bool:
    """Demande l'autorisation, ce qui inscrit l'application dans le panneau des
    Réglages système et y affiche l'invite du système.

    Distinction qui a coûté une inspection : `AXIsProcessTrusted` **constate**,
    elle n'inscrit rien. Une application qui ne demande jamais n'apparaît jamais
    dans la liste d'Accessibilité, et l'autorisation dont elle profite est alors
    celle d'un autre maillon de la chaîne, l'interpréteur par exemple, qui la perd
    à la première mise à jour changeant son chemin.

    Rend l'état au moment de l'appel : l'autorisation venant d'être demandée est
    encore fausse, l'utilisateur devant cocher la case et relancer.
    """
    return bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True}))


def envoyer(combinaison: str) -> None:
    """Envoie une combinaison à l'application au premier plan.

    Ne vérifie pas l'autorisation : l'appelant le fait une fois au lancement, pour
    ne pas payer l'appel à chaque frappe.
    """
    code, flags = analyser(combinaison)
    source = CGEventSourceCreate(kCGEventSourceStateHIDSystemState)
    for enfoncee in (True, False):
        evenement = CGEventCreateKeyboardEvent(source, code, enfoncee)
        CGEventSetFlags(evenement, flags)
        CGEventPost(kCGHIDEventTap, evenement)
        if enfoncee:
            time.sleep(DELAI_APPUI)


def _cli(arguments: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(
        prog="controle_vocal.clavier",
        description="Envoie une ou plusieurs combinaisons de touches, pour essai.",
    )
    analyseur.add_argument(
        "combinaisons",
        nargs="*",
        help="par exemple : droite, echap, cmd+alt+p",
    )
    analyseur.add_argument(
        "--delai",
        type=float,
        default=0.0,
        metavar="SECONDES",
        help="attente avant l'envoi, le temps de basculer sur la fenêtre visée",
    )
    analyseur.add_argument(
        "--liste",
        action="store_true",
        help="affiche les noms de touches reconnus, puis quitte",
    )
    options = analyseur.parse_args(arguments)

    if options.liste:
        print("Modificateurs :", ", ".join(sorted(set(MODIFICATEURS))))
        print("Touches :", ", ".join(TOUCHES))
        return 0

    if not options.combinaisons:
        analyseur.error("aucune combinaison donnée (voir --liste)")

    try:
        for combinaison in options.combinaisons:
            analyser(combinaison)
    except ErreurTouche as erreur:
        print(f"Erreur : {erreur}", file=sys.stderr)
        return 2

    if not accessibilite_accordee():
        print(
            "Autorisation Accessibilité absente pour ce terminal.\n"
            "Réglages système > Confidentialité et sécurité > Accessibilité,\n"
            "cocher l'application qui lance la commande, puis la relancer.",
            file=sys.stderr,
        )
        return 1

    if options.delai:
        print(f"Envoi dans {options.delai:g} s, basculez sur la fenêtre visée.")
        time.sleep(options.delai)

    for combinaison in options.combinaisons:
        envoyer(combinaison)
        print(f"envoyé : {combinaison}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
