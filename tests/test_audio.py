"""Choix du périphérique d'entrée. Le flux lui-même demande un micro, pas un test."""

from controle_vocal import audio


def test_index_donne_en_chaine_devient_un_entier() -> None:
    """Régression : `--micro 1` cherchait un périphérique *nommé* « 1 », jamais trouvé."""
    assert audio.resoudre_peripherique("1") == 1
    assert audio.Micro(peripherique="1").peripherique == 1


def test_nom_partiel_reste_une_chaine() -> None:
    assert audio.resoudre_peripherique("MacBook") == "MacBook"


def test_absence_de_choix_laisse_le_peripherique_par_defaut() -> None:
    assert audio.resoudre_peripherique(None) is None
    assert audio.resoudre_peripherique("  ") is None
