"""Ce que la pastille tient sans écran : la traduction des états et le temps.

Ce qui reste hors de portée d'un test, et se vérifie à l'œil par
`uv run -m controle_vocal.pastille --essai` : que la fenêtre passe bien au-dessus
d'une application en plein écran.
"""

from __future__ import annotations

import pytest

from controle_vocal.decision import Etat
from controle_vocal.pastille import (
    COINS,
    ErreurPastille,
    Pastille,
    Signal,
    SurfaceMuette,
    cadre_ecran,
    origine_pastille,
    ouvrir,
)


class Horloge:
    """Horloge de papier : elle n'avance que si on la pousse."""

    def __init__(self) -> None:
        self.instant = 0.0

    def __call__(self) -> float:
        return self.instant

    def avancer(self, secondes: float) -> None:
        self.instant += secondes


def pastille_de_test(duree: float = 1.0) -> tuple[Pastille, SurfaceMuette, Horloge]:
    surface = SurfaceMuette()
    horloge = Horloge()
    return Pastille(surface, duree=duree, horloge=horloge), surface, horloge


# --- Traduction des états du décideur ---------------------------------------


@pytest.mark.parametrize(
    "etat, attendu",
    [
        (Etat.ENTENDU, Signal.ENTENDU),
        (Etat.EXECUTE, Signal.EXECUTE),
        (Etat.INCOMPRIS, Signal.INCOMPRIS),
    ],
)
def test_les_trois_etats_visibles_ont_leur_signal(etat, attendu):
    assert Signal.depuis_etat(etat) is attendu


def test_ignore_n_allume_rien():
    """Le bruit de salle ne doit pas faire clignoter la pastille."""
    assert Signal.depuis_etat(Etat.IGNORE) is None


def test_un_etat_inconnu_n_allume_rien():
    assert Signal.depuis_etat("brouillard") is None


# --- Le temps de la pastille ------------------------------------------------


def test_signaler_pose_la_couleur():
    pastille, surface, _ = pastille_de_test()
    pastille.signaler(Signal.EXECUTE)
    assert surface.signal is Signal.EXECUTE
    assert pastille.signal is Signal.EXECUTE


def test_signaler_rien_laisse_la_pastille_eteinte():
    pastille, surface, _ = pastille_de_test()
    pastille.signaler(None)
    assert surface.journal == []
    assert pastille.signal is None


def test_la_pastille_reste_allumee_avant_l_echeance():
    pastille, surface, horloge = pastille_de_test(duree=1.0)
    pastille.signaler(Signal.ENTENDU)
    horloge.avancer(0.9)
    pastille.rafraichir()
    assert surface.signal is Signal.ENTENDU


def test_la_pastille_s_eteint_a_l_echeance():
    pastille, surface, horloge = pastille_de_test(duree=1.0)
    pastille.signaler(Signal.ENTENDU)
    horloge.avancer(1.0)
    pastille.rafraichir()
    assert surface.signal is None
    assert pastille.signal is None


def test_rafraichir_n_efface_qu_une_fois():
    """Sans quoi la boucle principale demanderait un effacement à chaque bloc."""
    pastille, surface, horloge = pastille_de_test(duree=1.0)
    pastille.signaler(Signal.EXECUTE)
    horloge.avancer(2.0)
    pastille.rafraichir()
    pastille.rafraichir()
    pastille.rafraichir()
    assert surface.journal.count("effacer") == 1


def test_rafraichir_sans_rien_d_allume_ne_fait_rien():
    pastille, surface, _ = pastille_de_test()
    pastille.rafraichir()
    assert surface.journal == []


def test_un_signal_en_remplace_un_autre_et_repousse_l_echeance():
    """Deux commandes de suite : la seconde couleur prend la place, sans trou noir."""
    pastille, surface, horloge = pastille_de_test(duree=1.0)
    pastille.signaler(Signal.ENTENDU)
    horloge.avancer(0.8)
    pastille.signaler(Signal.EXECUTE)
    horloge.avancer(0.5)
    pastille.rafraichir()
    assert surface.signal is Signal.EXECUTE
    assert surface.journal == ["poser:entendu", "poser:execute"]


def test_le_bloc_with_ferme_la_surface():
    surface = SurfaceMuette()
    with Pastille(surface) as pastille:
        pastille.signaler(Signal.EXECUTE)
    assert surface.journal[-1] == "fermer"
    assert pastille.signal is None


# --- Placement sur l'écran --------------------------------------------------


def test_les_quatre_coins_tombent_dans_l_ecran():
    cadre = (0.0, 0.0, 1440.0, 900.0)
    for coin in COINS:
        x, y = origine_pastille(cadre, taille=36, coin=coin, marge=40)
        assert 0 <= x <= 1440 - 36
        assert 0 <= y <= 900 - 36


def test_bas_droite_colle_au_bon_bord():
    x, y = origine_pastille((0.0, 0.0, 1440.0, 900.0), taille=36, coin="bas_droite", marge=40)
    assert (x, y) == (1440 - 36 - 40, 40)


def test_haut_gauche_colle_au_bon_bord():
    x, y = origine_pastille((0.0, 0.0, 1440.0, 900.0), taille=36, coin="haut_gauche", marge=40)
    assert (x, y) == (40, 900 - 36 - 40)


def test_un_ecran_decale_decale_la_pastille():
    """Un projecteur branché à droite du Mac a une origine non nulle."""
    x, y = origine_pastille(
        (1440.0, 0.0, 1920.0, 1080.0), taille=36, coin="bas_gauche", marge=40
    )
    assert (x, y) == (1440 + 40, 40)


def test_un_coin_inconnu_est_refuse():
    with pytest.raises(ErreurPastille):
        origine_pastille((0.0, 0.0, 1440.0, 900.0), coin="milieu")


def test_l_ecran_principal_a_une_taille():
    _, _, largeur, hauteur = cadre_ecran(0)
    assert largeur > 0 and hauteur > 0


def test_un_ecran_absent_echoue_au_lancement():
    """Un projecteur débranché doit se voir avant la séance, pas pendant."""
    with pytest.raises(ErreurPastille):
        cadre_ecran(99)


# --- Pastille éteinte -------------------------------------------------------


def test_la_pastille_desactivee_n_affiche_rien_mais_repond():
    """L'appelant n'a jamais à tester si la pastille existe."""
    pastille = ouvrir(active=False)
    pastille.signaler(Signal.EXECUTE)
    pastille.rafraichir()
    pastille.fermer()
    assert isinstance(pastille.surface, SurfaceMuette)
