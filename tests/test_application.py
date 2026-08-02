"""Détection de l'application au premier plan et choix du profil correspondant."""

import os
import subprocess
import time
from pathlib import Path

import pytest

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


@pytest.mark.skipif(
    os.environ.get("CONTROLE_VOCAL_TEST_FOCUS") != "1",
    reason="vole le focus des fenêtres : CONTROLE_VOCAL_TEST_FOCUS=1 pour le lancer",
)
def test_la_detection_suit_le_changement_de_fenetre() -> None:
    """Régression du 2026-08-02 : sans dépilage des notifications, `NSWorkspace`
    restait figé sur l'application présente au démarrage du processus."""
    for nom, attendu in [
        ("Finder", "com.apple.finder"),
        ("Terminal", "com.apple.Terminal"),
        ("Finder", "com.apple.finder"),
    ]:
        subprocess.run(
            ["osascript", "-e", f'tell application "{nom}" to activate'],
            capture_output=True,
            check=True,
        )
        time.sleep(0.8)
        courante = application.au_premier_plan()
        assert courante is not None and courante.bundle_id == attendu
