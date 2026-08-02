"""Boucle principale : écouter, décider, frapper. Le jalon 1 en un seul processus.

    uv run -m controle_vocal                     détection du profil, envoi réel
    uv run -m controle_vocal --profil canva      profil épinglé pour la séance
    uv run -m controle_vocal --simulation        tout sauf l'envoi des touches

Trois garanties tenues ici, et pas ailleurs :

- Ce qui peut échouer échoue au lancement, jamais devant le public : autorisation
  Accessibilité, modèle Vosk, touches des profils, micro.
- Un micro qui disparaît arrête l'outil sur un message clair au lieu de figer la
  séance : le clavier reprend la main, critère de succès n°4.
- Le profil suit l'application au premier plan, et la grammaire suit le profil.
"""

from __future__ import annotations

import argparse
import sys
import time

from controle_vocal import audio, clavier, pastille as module_pastille, profils
from controle_vocal.decision import (
    SEUIL_PAR_DEFAUT,
    TOLERANCE_PAR_DEFAUT,
    Decideur,
    ErreurDecision,
    Etat,
    charger_jeu,
)
from controle_vocal.reconnaissance import Reconnaisseur

#: Blocs d'un quart de seconde entre deux lectures de l'application au premier
#: plan. Une seconde suffit : on ne parle pas dans la seconde qui suit un
#: changement de fenêtre.
BLOCS_ENTRE_DEUX_LECTURES = 4

MESSAGE_ACCESSIBILITE = (
    "Autorisation Accessibilité absente pour ce terminal.\n"
    "Réglages système > Confidentialité et sécurité > Accessibilité,\n"
    "cocher l'application qui lance la commande, puis la relancer."
)


def verifier_touches(jeu: dict[str, profils.Profil]) -> list[str]:
    """Rend la liste des combinaisons qu'un CSV référence et que le clavier ignore.

    Vérifié au lancement plutôt qu'à la frappe : une touche mal orthographiée dans
    un CSV rempli à la main ne doit pas se découvrir en pleine présentation.
    """
    fautives = []
    for profil in jeu.values():
        for commande in profil.commandes_utilisables:
            if commande.est_action_interne:
                continue
            try:
                clavier.analyser(commande.touches)
            except clavier.ErreurTouche as erreur:
                fautives.append(f"{profil.nom}.csv, « {commande.nom} » : {erreur}")
    return fautives


def _accueil(
    profil: profils.Profil, decideur: Decideur, options: argparse.Namespace
) -> str:
    """Message d'ouverture, affiché une fois le micro réellement ouvert."""
    reveil = " ou ".join(f"« {mot} »" for mot in profil.mots_reveil)
    detection = (
        "épinglé" if decideur.epingle else "suit l'application au premier plan"
    )
    simulation = ", simulation : aucune touche ne partira" if options.simulation else ""
    surimpression = (
        f"\nPastille en surimpression, coin {options.pastille_coin.replace('_', ' ')} "
        f"de l'écran {options.pastille_ecran}."
        if options.pastille
        else ""
    )
    return (
        f"Écoute en cours. Mot de réveil {reveil}, puis la commande.\n"
        f"Profil « {profil.nom} » ({detection}), seuil {options.seuil:.2f}{simulation}"
        f"{surimpression}\n"
        "Pour arrêter : dites l'extinction, ou Ctrl+C."
    )


def _options(arguments: list[str] | None) -> argparse.Namespace:
    analyseur = argparse.ArgumentParser(
        prog="controle_vocal",
        description="Télécommande vocale : dites le mot de réveil, puis la commande.",
    )
    analyseur.add_argument(
        "--profil",
        metavar="NOM",
        help="épingle un profil pour la séance au lieu de le détecter",
    )
    analyseur.add_argument(
        "--seuil",
        type=float,
        default=SEUIL_PAR_DEFAUT,
        metavar="CERTITUDE",
        help=f"certitude minimale d'un énoncé (défaut : {SEUIL_PAR_DEFAUT:.2f})",
    )
    analyseur.add_argument(
        "--tolerance",
        type=int,
        default=TOLERANCE_PAR_DEFAUT,
        metavar="MOTS",
        help="mots parasites admis entre le mot de réveil et la commande",
    )
    analyseur.add_argument(
        "--micro",
        metavar="INDEX_OU_NOM",
        help="périphérique d'entrée (liste : uv run -m controle_vocal.audio --liste)",
    )
    analyseur.add_argument(
        "--simulation",
        action="store_true",
        help="décide et affiche tout, mais n'envoie aucune touche",
    )
    analyseur.add_argument(
        "--pastille",
        action="store_true",
        help="affiche la pastille d'état en surimpression sur la présentation",
    )
    analyseur.add_argument(
        "--pastille-coin",
        choices=module_pastille.COINS,
        default=module_pastille.COIN_PAR_DEFAUT,
        help="coin d'écran où poser la pastille",
    )
    analyseur.add_argument(
        "--pastille-ecran",
        type=int,
        default=0,
        metavar="INDEX",
        help="écran de projection (liste : uv run -m controle_vocal.pastille --liste)",
    )
    analyseur.add_argument(
        "--pastille-niveau",
        choices=tuple(module_pastille.NIVEAUX),
        default=module_pastille.NIVEAU_PAR_DEFAUT,
        help="hauteur de la fenêtre, à monter si elle passe sous le plein écran",
    )
    analyseur.add_argument(
        "--pastille-taille",
        type=int,
        default=module_pastille.TAILLE,
        metavar="POINTS",
        help=f"diamètre du disque (défaut : {module_pastille.TAILLE})",
    )
    analyseur.add_argument(
        "--pastille-duree",
        type=float,
        default=module_pastille.DUREE_SIGNAL,
        metavar="SECONDES",
        help=f"durée d'allumage (défaut : {module_pastille.DUREE_SIGNAL})",
    )
    return analyseur.parse_args(arguments)


def principal(arguments: list[str] | None = None) -> int:
    options = _options(arguments)

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

    if fautives := verifier_touches(jeu):
        print("Touches inconnues dans les profils :", file=sys.stderr)
        for faute in fautives:
            print(f"  {faute}", file=sys.stderr)
        print(
            "Noms reconnus : uv run -m controle_vocal.clavier --liste", file=sys.stderr
        )
        return 2

    if not options.simulation and not clavier.accessibilite_accordee():
        print(MESSAGE_ACCESSIBILITE, file=sys.stderr)
        return 1

    profil = decideur.rafraichir_profil()
    try:
        moteur = Reconnaisseur(profil.grammaire())
    except FileNotFoundError as erreur:
        print(f"Erreur : {erreur}", file=sys.stderr)
        return 2

    try:
        surimpression = module_pastille.ouvrir(
            active=options.pastille,
            coin=options.pastille_coin,
            ecran=options.pastille_ecran,
            taille=options.pastille_taille,
            niveau=options.pastille_niveau,
            duree=options.pastille_duree,
        )
    except module_pastille.ErreurPastille as erreur:
        print(f"Erreur : {erreur}", file=sys.stderr)
        return 2

    code = 0
    try:
        with surimpression, audio.Micro(
            taux=moteur.taux, peripherique=options.micro
        ) as micro:
            print(_accueil(profil, decideur, options))
            for numero, bloc in enumerate(micro):
                surimpression.rafraichir()
                if numero % BLOCS_ENTRE_DEUX_LECTURES == 0:
                    suivant = decideur.rafraichir_profil()
                    if suivant.nom != profil.nom:
                        profil = suivant
                        moteur.changer_grammaire(profil.grammaire())
                        print(f"  profil « {profil.nom} » ({profil.application})")

                enonce = moteur.alimenter(bloc)
                if enonce is None:
                    continue

                decision = decideur.traiter(enonce)
                if decision.etat is not Etat.IGNORE:
                    print(f"  {decision}")
                if decision.a_agir:
                    depart = time.perf_counter()
                    if not options.simulation:
                        clavier.envoyer(decision.touches)
                    duree = (time.perf_counter() - depart) * 1000
                    print(f"    touches « {decision.touches} » en {duree:.0f} ms")

                # La pastille s'allume après la frappe, jamais avant : dessiner
                # coûte une vingtaine de millisecondes, que la diapositive n'a
                # pas à attendre. À l'œil, les deux sont simultanés.
                surimpression.signaler(
                    module_pastille.Signal.depuis_etat(decision.etat)
                )
                if decideur.arret_demande:
                    break
    except audio.ErreurMicro as erreur:
        print(
            f"\nMicro perdu : {erreur}\n"
            "L'outil s'arrête, la présentation continue au clavier.",
            file=sys.stderr,
        )
        code = 1
    except KeyboardInterrupt:
        pass

    print("\nÉcoute arrêtée.")
    return code


if __name__ == "__main__":
    raise SystemExit(principal())
