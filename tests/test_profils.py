"""Critère de l'étape 1 : charger canva.csv, lister les phrases, résoudre un synonyme."""

from pathlib import Path

import pytest

from controle_vocal import profils

DOSSIER_PROFILS = Path(__file__).resolve().parents[1] / "profils"


@pytest.fixture
def canva() -> profils.Profil:
    return profils.charger(DOSSIER_PROFILS / "canva.csv")


def test_phrases_acceptees(canva: profils.Profil) -> None:
    phrases = canva.phrases_acceptees()
    assert "suivante" in phrases
    assert "suite" in phrases
    assert "précédente" in phrases
    # Les lignes sans touche établie sont hors grammaire tant qu'elles ne sont pas
    # vérifiées à la main (étape 4 du plan).
    assert "noir" not in phrases
    assert "début" not in phrases


def test_synonyme_resout_vers_la_meme_touche(canva: profils.Profil) -> None:
    assert canva.resoudre("suite") == canva.resoudre("suivante")
    assert canva.resoudre("suivante").touches == "droite"


def test_resolution_tolere_casse_et_ponctuation(canva: profils.Profil) -> None:
    assert canva.resoudre("Suivante !") == canva.resoudre("suivante")


def test_phrase_inconnue_ou_desactivee_ne_resout_pas(canva: profils.Profil) -> None:
    assert canva.resoudre("chauffe le café") is None
    assert canva.resoudre("noir") is None


def test_mot_reveil_hors_des_commandes(canva: profils.Profil) -> None:
    assert canva.mots_reveil == ("higgins",)
    assert canva.resoudre("higgins") is None


def test_grammaire_colle_le_reveil_a_chaque_commande(canva: profils.Profil) -> None:
    grammaire = canva.grammaire()
    assert grammaire[-1] == profils.JETON_INCONNU
    assert "higgins suivante" in grammaire
    assert "higgins" not in grammaire
    assert len(grammaire) == len(canva.phrases_acceptees()) + 1


def test_actions_internes_toujours_presentes() -> None:
    """Un profil qui omet la pause ou le coupe-circuit se les voit ajoutées."""
    minimal = profils.charger(DOSSIER_PROFILS / "canva.csv")
    assert minimal.resoudre("extinction").touches == "@quitter"
    assert minimal.resoudre("pause").touches == "@pause"


def test_profil_defaut_sans_touche_destructrice() -> None:
    defaut = profils.charger(DOSSIER_PROFILS / "defaut.csv")
    touches = {c.touches for c in defaut.commandes_utilisables}
    assert touches <= {"droite", "gauche", "echap", "@pause", "@reprise", "@quitter"}


def test_gabarit_vide_se_charge_sans_commande() -> None:
    gabarit = profils.charger(DOSSIER_PROFILS / "_gabarit.csv")
    assert gabarit.phrases_acceptees() == ()


def test_gabarit_exclu_du_chargement_en_masse() -> None:
    tous = profils.charger_tous(DOSSIER_PROFILS)
    assert set(tous) == {"canva", "defaut"}


def test_phrase_en_double_est_refusee(tmp_path: Path) -> None:
    fichier = tmp_path / "doublon.csv"
    fichier.write_text(
        "application,bundle_id,commande,touches,phrases,actif\n"
        "Test,,suivante,droite,avance,oui\n"
        "Test,,precedente,gauche,avance,oui\n",
        encoding="utf-8",
    )
    with pytest.raises(profils.ErreurProfil, match="imprévisible"):
        profils.charger(fichier)


def test_colonne_absente_est_refusee(tmp_path: Path) -> None:
    fichier = tmp_path / "tronque.csv"
    fichier.write_text("application,commande,touches\nTest,suivante,droite\n", encoding="utf-8")
    with pytest.raises(profils.ErreurProfil, match="colonnes absentes"):
        profils.charger(fichier)


def test_repli_sur_defaut_pour_application_inconnue() -> None:
    tous = profils.charger_tous(DOSSIER_PROFILS)
    assert profils.profil_pour_bundle(tous, "com.inconnue.app").nom == "defaut"
