"""Critère de l'étape 16 : l'interrupteur lance, arrête, et ne ment jamais sur l'état.

La commande réelle est remplacée par de faux programmes : ces tests éprouvent la
conduite du processus, pas la boucle d'écoute, et n'ouvrent aucun micro.
"""

import sys
import time
from pathlib import Path

import pytest

from controle_vocal.reglages.moteur import ErreurMoteur, Moteur, argv_par_defaut

RACINE = Path(__file__).resolve().parents[1]

#: Faux outil qui tourne jusqu'à ce qu'on l'arrête, en annonçant son démarrage.
QUI_DURE = "import time, sys; print('en écoute', flush=True); time.sleep(60)"

#: Faux outil qui échoue au lancement, comme un micro absent.
QUI_ECHOUE = "import sys; print('Micro introuvable', flush=True); sys.exit(2)"

#: Faux outil qui ignore Ctrl+C, pour éprouver l'escalade des signaux.
QUI_RESISTE = (
    "import signal, time, sys; signal.signal(signal.SIGINT, signal.SIG_IGN); "
    "print('sourd', flush=True); time.sleep(60)"
)


def moteur_avec(script: str) -> Moteur:
    return Moteur(RACINE, fabriquer_argv=lambda profil, pastille: [sys.executable, "-c", script])


def attendre(condition, limite: float = 5.0) -> bool:
    """Attend qu'une condition devienne vraie. Un processus ne démarre ni ne meurt
    à l'instant où on le demande."""
    echeance = time.monotonic() + limite
    while time.monotonic() < echeance:
        if condition():
            return True
        time.sleep(0.05)
    return False


# --- Marche et arrêt --------------------------------------------------------


def test_demarre_puis_arrete() -> None:
    moteur = moteur_avec(QUI_DURE)
    assert not moteur.actif

    moteur.demarrer()
    assert attendre(lambda: moteur.actif)
    assert moteur.etat()["pid"]

    moteur.arreter()
    assert not moteur.actif
    assert moteur.etat()["pid"] is None


def test_demarrer_deux_fois_est_refuse() -> None:
    moteur = moteur_avec(QUI_DURE)
    moteur.demarrer()
    try:
        with pytest.raises(ErreurMoteur, match="tourne déjà"):
            moteur.demarrer()
    finally:
        moteur.fermer()


def test_arreter_ce_qui_ne_tourne_pas_est_refuse() -> None:
    with pytest.raises(ErreurMoteur, match="ne tourne pas"):
        moteur_avec(QUI_DURE).arreter()


def test_fermer_est_sans_effet_si_rien_ne_tourne() -> None:
    moteur_avec(QUI_DURE).fermer()  # ne lève pas


def test_un_outil_sourd_finit_par_etre_tue() -> None:
    """L'escalade Ctrl+C puis SIGTERM puis SIGKILL n'est pas décorative."""
    moteur = moteur_avec(QUI_RESISTE)
    moteur.demarrer()
    assert attendre(lambda: "sourd" in moteur.etat()["journal"])
    moteur.arreter()
    assert not moteur.actif


# --- L'état dit la vérité ---------------------------------------------------


def test_un_outil_mort_tout_seul_apparait_arrete() -> None:
    """Le cas qui compte : le micro disparaît en séance, l'outil s'arrête, et
    l'interrupteur doit le dire au lieu d'afficher « en marche »."""
    moteur = moteur_avec(QUI_ECHOUE)
    moteur.demarrer()
    assert attendre(lambda: not moteur.actif)

    etat = moteur.etat()
    assert etat["actif"] is False
    assert etat["code_retour"] == 2
    assert "Micro introuvable" in etat["journal"]


def test_la_sortie_de_l_outil_est_gardee() -> None:
    moteur = moteur_avec(QUI_DURE)
    moteur.demarrer()
    try:
        assert attendre(lambda: "en écoute" in moteur.etat()["journal"])
    finally:
        moteur.fermer()


def test_la_sortie_arrive_sans_attendre_la_mort_de_l_outil() -> None:
    """Régression trouvée à l'essai : sans `PYTHONUNBUFFERED`, un `print` sans
    `flush` reste en tampon tant que le processus vit, et l'interface n'affiche
    rien pendant la marche, c'est-à-dire quand c'est utile."""
    moteur = moteur_avec("import time; print('démarré'); time.sleep(60)")
    moteur.demarrer()
    try:
        assert attendre(lambda: "démarré" in moteur.etat()["journal"])
    finally:
        moteur.fermer()


def test_les_options_sont_rendues_telles_que_demandees() -> None:
    moteur = moteur_avec(QUI_DURE)
    moteur.demarrer(profil="canva", pastille=True)
    try:
        assert moteur.etat()["options"] == {"profil": "canva", "pastille": True}
    finally:
        moteur.fermer()


def test_un_relancement_efface_la_sortie_precedente() -> None:
    moteur = moteur_avec(QUI_ECHOUE)
    moteur.demarrer()
    assert attendre(lambda: not moteur.actif)
    moteur.demarrer()
    assert attendre(lambda: not moteur.actif)
    assert moteur.etat()["journal"].count("Micro introuvable") == 1


def test_commande_introuvable_donne_une_erreur_lisible() -> None:
    moteur = Moteur(RACINE, fabriquer_argv=lambda p, q: ["/binaire/qui/n/existe/pas"])
    with pytest.raises(ErreurMoteur, match="lancement impossible"):
        moteur.demarrer()
    assert not moteur.actif


# --- La commande réelle -----------------------------------------------------


def test_argv_par_defaut_reprend_les_options() -> None:
    assert argv_par_defaut(None, False) == [sys.executable, "-m", "controle_vocal"]
    assert argv_par_defaut("canva", True) == [
        sys.executable,
        "-m",
        "controle_vocal",
        "--profil",
        "canva",
        "--pastille",
    ]
