"""Capture du micro en flux continu, en blocs prêts pour le moteur de reconnaissance.

Le son ne fait que passer : aucun enregistrement, aucun fichier, aucun envoi. C'est
la contrainte de vie privée du projet, le micro tournant devant du public.

Un micro qui disparaît en cours de séance lève `ErreurMicro` plutôt que de figer la
boucle : la présentation continue au clavier, critère de succès n°4.

    uv run -m controle_vocal.audio --liste
"""

from __future__ import annotations

import argparse
import queue
from typing import Iterator

import sounddevice

#: Échantillons par bloc : un quart de seconde à 16 kHz. Assez court pour que la
#: frappe suive la phrase de près, assez long pour ne pas hacher les mots.
TAILLE_BLOC = 4000

TAUX = 16000


class ErreurMicro(Exception):
    """Micro absent, occupé, ou disparu en cours de séance."""


class Micro:
    """Flux du micro, à parcourir bloc par bloc dans un `with`.

        with Micro() as micro:
            for bloc in micro:
                ...
    """

    def __init__(
        self,
        taux: int = TAUX,
        peripherique: int | str | None = None,
        taille_bloc: int = TAILLE_BLOC,
    ) -> None:
        self.taux = taux
        self.peripherique = resoudre_peripherique(peripherique)
        self.taille_bloc = taille_bloc
        self._blocs: queue.Queue[bytes] = queue.Queue()
        self._incident: str | None = None
        self._flux: sounddevice.RawInputStream | None = None

    def _recevoir(self, donnees, _images: int, _horodatage, statut) -> None:
        """Appelé par le pilote audio, hors du fil principal."""
        if statut:
            self._incident = str(statut)
        self._blocs.put(bytes(donnees))

    def __enter__(self) -> "Micro":
        try:
            self._flux = sounddevice.RawInputStream(
                samplerate=self.taux,
                blocksize=self.taille_bloc,
                device=self.peripherique,
                dtype="int16",
                channels=1,
                callback=self._recevoir,
            )
            self._flux.start()
        except Exception as erreur:
            raise ErreurMicro(f"micro indisponible : {erreur}") from erreur
        return self

    def __exit__(self, *_exception) -> None:
        if self._flux is not None:
            self._flux.stop()
            self._flux.close()
            self._flux = None

    def __iter__(self) -> Iterator[bytes]:
        while True:
            if self._flux is None:
                raise ErreurMicro("le flux du micro est fermé")
            try:
                bloc = self._blocs.get(timeout=5.0)
            except queue.Empty as erreur:
                raise ErreurMicro(
                    "le micro ne rend plus de son depuis cinq secondes, "
                    "il a peut-être été débranché"
                ) from erreur
            yield bloc


def resoudre_peripherique(valeur: str | int | None) -> int | str | None:
    """Traduit ce que la ligne de commande donne en ce que `sounddevice` attend.

    Un index arrive de `argparse` sous forme de chaîne, et `sounddevice` cherche
    alors un périphérique dont le *nom* vaut « 1 », qu'il ne trouve jamais. Un
    nom partiel reste accepté tel quel : « MacBook » suffit.
    """
    if valeur is None or isinstance(valeur, int):
        return valeur
    valeur = valeur.strip()
    if not valeur:
        return None
    return int(valeur) if valeur.lstrip("-").isdigit() else valeur


def peripheriques() -> list[dict]:
    """Périphériques capables d'enregistrer, avec leur position dans la liste."""
    return [
        {"index": index, "nom": info["name"], "voies": info["max_input_channels"]}
        for index, info in enumerate(sounddevice.query_devices())
        if info["max_input_channels"] > 0
    ]


def _cli(arguments: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(
        prog="controle_vocal.audio",
        description="Inspecte les entrées audio de la machine.",
    )
    analyseur.add_argument(
        "--liste", action="store_true", help="liste les micros disponibles"
    )
    options = analyseur.parse_args(arguments)

    defaut = sounddevice.default.device[0]
    for peripherique in peripheriques():
        marque = " (par défaut)" if peripherique["index"] == defaut else ""
        print(f"  {peripherique['index']}  {peripherique['nom']}{marque}")
    if not options.liste:
        print("\nPour écouter réellement : uv run -m controle_vocal.reconnaissance")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
