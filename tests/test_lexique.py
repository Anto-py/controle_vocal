"""Le contrôle du mot de réveil face au vrai moteur, pas à une doublure.

Ce que ces tests protègent tient à une découverte faite à l'essai : un mot absent
du lexique n'est pas une erreur pour Vosk. Il l'écarte de la grammaire, écrit un
avertissement, et continue. La télécommande démarrerait donc sans rien dire et ne
répondrait jamais. L'avertissement venant de la couche C++, il ne s'attrape qu'en
détournant le descripteur de sortie d'erreur du système : c'est cette mécanique-là
qu'on éprouve ici, et elle ne se laisse pas simuler.

Le modèle pèse une quarantaine de mégaoctets et met une seconde ou deux à
s'ouvrir : ces tests sont les seuls du dépôt à le charger.
"""

import os

import pytest

vosk = pytest.importorskip("vosk", reason="Vosk absent")

from controle_vocal import chemins, reconnaissance  # noqa: E402

MODELE_PRESENT = any(chemins.dossier_modeles().glob("vosk-model-*"))

pytestmark = pytest.mark.skipif(
    not MODELE_PRESENT, reason="aucun modèle Vosk installé"
)


def test_un_mot_du_francais_est_connu() -> None:
    assert reconnaissance.mots_hors_lexique(["higgins"]) == []


def test_un_mot_invente_est_signale() -> None:
    assert reconnaissance.mots_hors_lexique(["zorglubtruc"]) == ["zorglubtruc"]


def test_seul_le_mot_fautif_est_rendu() -> None:
    """Le message doit désigner le mot à changer, pas la formulation entière."""
    assert reconnaissance.mots_hors_lexique(["zorglubtruc pause"]) == ["zorglubtruc"]


def test_les_formulations_d_origine_sont_toutes_connues() -> None:
    """Sinon l'outil livré ne répondrait pas à ses propres mots."""
    from controle_vocal import actions

    toutes = [
        phrase for phrases in actions.DEFAUTS.values() for phrase in phrases
    ]
    assert reconnaissance.mots_hors_lexique(toutes) == []


def test_une_liste_vide_ne_charge_rien() -> None:
    assert reconnaissance.mots_hors_lexique([]) == []


def test_la_sortie_d_erreur_est_rendue_intacte(capfd: pytest.CaptureFixture) -> None:
    """Le détournement du descripteur 2 doit se défaire, quoi qu'il arrive : un
    serveur qui perdrait sa sortie d'erreur deviendrait muet sur ses pannes.

    `capfd` et non `capsys` : c'est le descripteur du système qui est en jeu, pas
    l'objet Python, et lui seul voit ce qu'écrit une bibliothèque en C.
    """
    reconnaissance.mots_hors_lexique(["zorglubtruc"])
    os.write(2, b"toujours la\n")
    sortie = capfd.readouterr().err
    assert "toujours la" in sortie
    # L'avertissement de Vosk a été capté, il n'a pas filé dans le terminal.
    assert "Ignoring word" not in sortie
