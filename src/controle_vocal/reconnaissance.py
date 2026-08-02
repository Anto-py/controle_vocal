"""Reconnaissance hors ligne à vocabulaire fermé, par Vosk.

Le moteur ne reçoit que les énoncés attendus du profil actif, plus le jeton qui
absorbe le reste : tout ce qui n'y figure pas est rejeté au lieu d'être approché.
Rien ne sort de la machine, rien n'est écrit sur disque.

Essai sur un fichier, sans micro ni action :

    uv run -m controle_vocal.reconnaissance --fichier essai.wav
"""

from __future__ import annotations

import argparse
import json
import sys
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from vosk import KaldiRecognizer, Model, SetLogLevel

from controle_vocal import profils

#: Taux d'échantillonnage attendu par les modèles Vosk français.
TAUX = 16000

#: Emplacement du modèle, relatif à la racine du projet. Voir le README pour
#: la commande de téléchargement.
DOSSIER_MODELES = "modeles"

#: Jeton que Vosk rend quand il n'a rien reconnu de la grammaire.
TEXTE_INCONNU = profils.JETON_INCONNU


@dataclass(frozen=True)
class Enonce:
    """Un segment reconnu, avec la certitude que le moteur lui accorde."""

    texte: str
    certitude: float
    mots: tuple[tuple[str, float], ...]

    @property
    def vide(self) -> bool:
        return not self.texte or self.texte == TEXTE_INCONNU

    def __str__(self) -> str:
        detail = "  ".join(f"{mot} {score:.2f}" for mot, score in self.mots)
        return f"« {self.texte} »  certitude {self.certitude:.2f}   [{detail}]"


def racine_projet() -> Path:
    """Racine du dépôt, d'où se résolvent `modeles/` et `profils/`."""
    return Path(__file__).resolve().parents[2]


def chemin_modele(nom: str | None = None) -> Path:
    """Trouve le modèle téléchargé. Sans nom donné, prend le seul présent."""
    dossier = racine_projet() / DOSSIER_MODELES
    if nom:
        return dossier / nom
    candidats = sorted(c for c in dossier.glob("vosk-model-*") if c.is_dir())
    if not candidats:
        raise FileNotFoundError(
            f"aucun modèle Vosk dans {dossier}. "
            "Voir la commande de téléchargement dans le README."
        )
    return candidats[0]


class Reconnaisseur:
    """Moteur Vosk contraint à la grammaire d'un profil.

    La grammaire se reconstruit en changeant de profil : `changer_grammaire`.
    """

    def __init__(
        self,
        grammaire: list[str],
        modele: Path | None = None,
        taux: int = TAUX,
        bavard: bool = False,
    ) -> None:
        SetLogLevel(0 if bavard else -1)
        self.taux = taux
        self._modele = Model(str(modele or chemin_modele()))
        self._grammaire: list[str] = []
        self.changer_grammaire(grammaire)

    @property
    def grammaire(self) -> list[str]:
        return list(self._grammaire)

    def changer_grammaire(self, grammaire: list[str]) -> None:
        """Repart d'un moteur neuf : un `KaldiRecognizer` porte sa grammaire à vie."""
        self._grammaire = list(grammaire)
        self._moteur = KaldiRecognizer(
            self._modele, self.taux, json.dumps(self._grammaire, ensure_ascii=False)
        )
        self._moteur.SetWords(True)

    def alimenter(self, bloc: bytes) -> Enonce | None:
        """Rend un énoncé quand le moteur juge la phrase terminée, sinon rien."""
        if self._moteur.AcceptWaveform(bloc):
            return self._lire(self._moteur.Result())
        return None

    def reste(self) -> Enonce | None:
        """Vide le moteur en fin de flux, pour ne pas perdre le dernier énoncé."""
        return self._lire(self._moteur.FinalResult())

    @staticmethod
    def _lire(resultat_json: str) -> Enonce | None:
        brut = json.loads(resultat_json)
        texte = (brut.get("text") or "").strip()
        if not texte:
            return None
        mots = tuple(
            (m["word"], float(m.get("conf", 0.0))) for m in brut.get("result", ())
        )
        certitude = sum(score for _, score in mots) / len(mots) if mots else 0.0
        return Enonce(texte=texte, certitude=certitude, mots=mots)


def lire_wav(chemin: str | Path, taille_bloc: int = 4000) -> Iterable[bytes]:
    """Découpe un WAV mono 16 bits en blocs, pour éprouver le moteur sans micro."""
    with wave.open(str(chemin), "rb") as fichier:
        if fichier.getnchannels() != 1 or fichier.getsampwidth() != 2:
            raise ValueError(f"{chemin} : il faut un WAV mono 16 bits")
        while bloc := fichier.readframes(taille_bloc):
            yield bloc


def _cli(arguments: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(
        prog="controle_vocal.reconnaissance",
        description="Affiche tout ce qui est reconnu, sans rien exécuter.",
    )
    analyseur.add_argument(
        "--profil",
        default="canva",
        help="profil dont la grammaire contraint le moteur (défaut : canva)",
    )
    analyseur.add_argument(
        "--fichier",
        metavar="WAV",
        help="éprouve le moteur sur un WAV mono 16 bits au lieu du micro",
    )
    analyseur.add_argument(
        "--grammaire",
        action="store_true",
        help="affiche la grammaire soumise au moteur, puis quitte",
    )
    analyseur.add_argument(
        "--bavard",
        action="store_true",
        help="laisse Vosk écrire ses propres journaux",
    )
    options = analyseur.parse_args(arguments)

    chemin_profil = racine_projet() / "profils" / f"{options.profil}.csv"
    try:
        profil = profils.charger(chemin_profil)
    except profils.ErreurProfil as erreur:
        print(f"Erreur : {erreur}", file=sys.stderr)
        return 2

    grammaire = profil.grammaire()
    if options.grammaire:
        for entree in grammaire:
            print(entree)
        return 0

    try:
        moteur = Reconnaisseur(grammaire, bavard=options.bavard)
    except FileNotFoundError as erreur:
        print(f"Erreur : {erreur}", file=sys.stderr)
        return 2

    if options.fichier:
        for bloc in lire_wav(options.fichier):
            if enonce := moteur.alimenter(bloc):
                print(enonce)
        if enonce := moteur.reste():
            print(enonce)
        return 0

    from controle_vocal import audio

    print(
        f"Écoute en cours, profil « {profil.nom} », Ctrl+C pour arrêter.\n"
        f"Rien n'est exécuté : cet essai affiche seulement ce qui est reconnu."
    )
    try:
        with audio.Micro(taux=moteur.taux) as micro:
            for bloc in micro:
                if enonce := moteur.alimenter(bloc):
                    print(f"  {enonce}")
    except audio.ErreurMicro as erreur:
        print(f"Erreur : {erreur}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        if enonce := moteur.reste():
            print(f"  {enonce}")
        print("\nÉcoute arrêtée.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
