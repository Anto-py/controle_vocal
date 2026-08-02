"""Détection de l'application au premier plan et choix du profil correspondant."""

from pathlib import Path

from controle_vocal import application, profils

DOSSIER_PROFILS = Path(__file__).resolve().parents[1] / "profils"


def test_le_systeme_signale_une_application() -> None:
    courante = application.au_premier_plan()
    assert courante is not None
    assert courante.nom


def test_le_bundle_de_canva_choisit_le_profil_canva() -> None:
    tous = profils.charger_tous(DOSSIER_PROFILS)
    choisi = profils.profil_pour_bundle(tous, "com.canva.CanvaDesktop")
    assert choisi.nom == "canva"


def test_application_inconnue_replie_sur_defaut() -> None:
    tous = profils.charger_tous(DOSSIER_PROFILS)
    assert profils.profil_pour_bundle(tous, "com.google.Chrome").nom == "defaut"
    assert profils.profil_pour_bundle(tous, "").nom == "defaut"
