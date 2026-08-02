"""Analyse des combinaisons de touches. L'envoi réel se vérifie à la main (étape 2)."""

import pytest

from controle_vocal import clavier


def test_touche_seule() -> None:
    code, flags = clavier.analyser("droite")
    assert code == 0x7C
    assert flags == 0


def test_combinaison_a_modificateurs_multiples() -> None:
    code, flags = clavier.analyser("cmd+alt+p")
    assert code == 0x23
    assert flags == clavier.MODIFICATEURS["cmd"] | clavier.MODIFICATEURS["alt"]


def test_casse_et_espaces_toleres() -> None:
    assert clavier.analyser(" CMD + Alt + P ") == clavier.analyser("cmd+alt+p")


def test_synonymes_de_modificateurs() -> None:
    assert clavier.analyser("option+echap") == clavier.analyser("alt+echap")
    assert clavier.analyser("commande+a") == clavier.analyser("cmd+a")


@pytest.mark.parametrize("entree", ["", "  ", "+", "cmd+", "cmd"])
def test_combinaison_sans_touche_refusee(entree: str) -> None:
    with pytest.raises(clavier.ErreurTouche):
        clavier.analyser(entree)


def test_touche_inconnue_refusee() -> None:
    with pytest.raises(clavier.ErreurTouche, match="touche inconnue"):
        clavier.analyser("bidule")


def test_modificateur_inconnu_refuse() -> None:
    with pytest.raises(clavier.ErreurTouche, match="modificateur inconnu"):
        clavier.analyser("super+p")


def test_toutes_les_touches_des_profils_sont_analysables() -> None:
    """Garde-fou : aucun CSV ne peut référencer une touche que le module ignore."""
    from pathlib import Path

    from controle_vocal import profils

    dossier = Path(__file__).resolve().parents[1] / "profils"
    for profil in profils.charger_tous(dossier).values():
        for commande in profil.commandes_utilisables:
            if commande.est_action_interne:
                continue
            clavier.analyser(commande.touches)
