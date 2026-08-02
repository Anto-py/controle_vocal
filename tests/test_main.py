"""Critère de l'étape 7 : ce qui peut échouer échoue au lancement, pas en séance.

Ce que ces tests ne couvrent pas : la boucle elle-même, qui demande un micro et une
voix. Elle se vérifie à l'essai, pas ici.
"""

from pathlib import Path

from controle_vocal import __main__ as principal
from controle_vocal import profils

DOSSIER_PROFILS = Path(__file__).resolve().parents[1] / "profils"


def test_les_profils_livres_n_ont_que_des_touches_connues() -> None:
    assert principal.verifier_touches(profils.charger_tous(DOSSIER_PROFILS)) == []


def test_une_touche_inconnue_est_signalee(tmp_path: Path) -> None:
    csv = tmp_path / "essai.csv"
    csv.write_text(
        "application,bundle_id,commande,touches,phrases,actif\n"
        "Essai,com.essai,suivante,bidule,suivante,oui\n",
        encoding="utf-8",
    )
    fautives = principal.verifier_touches({"essai": profils.charger(csv)})
    assert len(fautives) == 1 and "bidule" in fautives[0]


def test_profil_epingle_introuvable_arrete_avant_d_ecouter(capsys) -> None:
    assert principal.principal(["--profil", "powerpoint"]) == 2
    assert "powerpoint" in capsys.readouterr().err
