"""Dessin de l'icône de l'application, en PNG écrit à la main.

Pourquoi pas une bibliothèque d'images : le projet n'a que des dépendances qui
servent à écouter et à frapper, et une icône ne vaut pas d'en ajouter une. Un PNG
sans compression est une suite d'octets simple, et un disque se calcule.

Le motif reprend la pastille d'état, emblème de l'outil : un disque posé sur la
projection, dans les couleurs de la charte.
"""

from __future__ import annotations

import struct
import zlib

# Charte rétrofuturisme.
INK = (13, 22, 23)
TEAL = (18, 118, 118)
JAUNE = (227, 165, 53)
ORANGE = (228, 99, 46)

#: Échantillons par côté de pixel. Sans lui, les bords du disque seraient en
#: escalier, ce qui se voit surtout aux petites tailles.
SUPER = 4


def _couverture(x: float, y: float, centre: float, rayon: float) -> float:
    """Part du pixel couverte par le disque, estimée par sur-échantillonnage."""
    dedans = 0
    for sous_y in range(SUPER):
        for sous_x in range(SUPER):
            px = x + (sous_x + 0.5) / SUPER - centre
            py = y + (sous_y + 0.5) / SUPER - centre
            if px * px + py * py <= rayon * rayon:
                dedans += 1
    return dedans / (SUPER * SUPER)


def _melanger(fond: tuple[int, int, int], dessus: tuple[int, int, int], part: float):
    return tuple(round(f + (d - f) * part) for f, d in zip(fond, dessus))


def dessiner(taille: int) -> bytes:
    """Rend l'icône en PNG : fond sombre à coins arrondis, disque teal, cœur jaune."""
    centre = taille / 2
    coin = taille * 0.22
    rayons = ((taille * 0.34, TEAL), (taille * 0.22, ORANGE), (taille * 0.13, JAUNE))

    lignes = bytearray()
    for y in range(taille):
        lignes.append(0)  # filtre « aucun », une fois par ligne
        for x in range(taille):
            # Coins arrondis : hors du rectangle adouci, le pixel est transparent.
            alpha = _alpha_coins(x, y, taille, coin)
            couleur = INK
            for rayon, teinte in rayons:
                part = _couverture(x, y, centre, rayon)
                if part:
                    couleur = _melanger(couleur, teinte, part)
            lignes += bytes((*couleur, round(alpha * 255)))

    return _png(taille, bytes(lignes))


def _alpha_coins(x: int, y: int, taille: int, coin: float) -> float:
    """Adoucit les quatre coins, un carré net jurerait au milieu des icônes macOS."""
    dedans = 0
    for sous_y in range(SUPER):
        for sous_x in range(SUPER):
            px = x + (sous_x + 0.5) / SUPER
            py = y + (sous_y + 0.5) / SUPER
            dx = max(coin - px, px - (taille - coin), 0.0)
            dy = max(coin - py, py - (taille - coin), 0.0)
            if dx * dx + dy * dy <= coin * coin:
                dedans += 1
    return dedans / (SUPER * SUPER)


def _bloc(nom: bytes, donnees: bytes) -> bytes:
    return (
        struct.pack(">I", len(donnees))
        + nom
        + donnees
        + struct.pack(">I", zlib.crc32(nom + donnees) & 0xFFFFFFFF)
    )


def _png(taille: int, pixels: bytes) -> bytes:
    entete = struct.pack(">IIBBBBB", taille, taille, 8, 6, 0, 0, 0)  # RVBA, 8 bits
    return (
        b"\x89PNG\r\n\x1a\n"
        + _bloc(b"IHDR", entete)
        + _bloc(b"IDAT", zlib.compress(pixels, 9))
        + _bloc(b"IEND", b"")
    )
