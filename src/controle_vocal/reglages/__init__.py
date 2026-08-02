"""Interface de réglages : page web locale qui lit et écrit les profils CSV.

Processus distinct de la boucle d'écoute, lancé avant un exposé et jamais pendant.
"""

from controle_vocal.reglages.serveur import PORT_PAR_DEFAUT, Reglages, router

__all__ = ["PORT_PAR_DEFAUT", "Reglages", "router"]
