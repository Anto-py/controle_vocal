/* Exécutable de « Contrôle vocal.app ».
 *
 * Pourquoi un binaire compilé plutôt qu'un script shell, qui suffisait à lancer
 * un serveur : macOS n'accorde pas d'autorisation à un script. Le processus qui
 * tourne alors est /bin/bash, un binaire d'Apple, et lui attribuer l'accès à
 * l'Accessibilité reviendrait à l'accorder à tout script du système. L'app
 * n'apparaissait donc jamais dans le panneau des Réglages système, et empruntait
 * l'autorisation d'un autre maillon de sa chaîne.
 *
 * Deuxième raison d'être de ce fichier, et elle commande sa structure : le
 * lanceur ne se remplace PAS par uv (pas d'exec direct). Il duplique le
 * processus et attend son enfant. Le binaire signé reste ainsi vivant pendant
 * toute la séance, et c'est lui que le système tient pour responsable de ce que
 * fait sa descendance. Un exec l'aurait effacé, avec l'identité qu'on cherche
 * précisément à lui donner.
 *
 * Compilé par outils/fabriquer_app.py, qui y injecte les chemins de la machine.
 */

#include <arpa/inet.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#ifndef PROJET
#define PROJET "."
#endif
#ifndef CHEMIN_UV
#define CHEMIN_UV "/opt/homebrew/bin/uv"
#endif
#ifndef PORT
#define PORT 8730
#endif

/* Une app lancée depuis le Finder n'a pas de terminal où écrire : sans cette
 * alerte, tout échec la ferait disparaître en silence. */
static void alerte(const char *message) {
    char commande[2048];
    snprintf(commande, sizeof commande,
             "/usr/bin/osascript -e 'display alert \"Contrôle vocal\" message \"%s\" "
             "as critical' >/dev/null 2>&1",
             message);
    system(commande);
}

/* Un second double-clic ne doit pas lancer un serveur de plus : le port serait
 * pris, et l'app échouerait sur un geste distrait. */
static int serveur_deja_la(void) {
    int prise = socket(AF_INET, SOCK_STREAM, 0);
    if (prise < 0) {
        return 0;
    }
    struct sockaddr_in adresse;
    memset(&adresse, 0, sizeof adresse);
    adresse.sin_family = AF_INET;
    adresse.sin_port = htons(PORT);
    adresse.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    int joignable = connect(prise, (struct sockaddr *)&adresse, sizeof adresse) == 0;
    close(prise);
    return joignable;
}

int main(void) {
    if (serveur_deja_la()) {
        char commande[256];
        snprintf(commande, sizeof commande, "/usr/bin/open http://127.0.0.1:%d/", PORT);
        system(commande);
        return 0;
    }

    if (chdir(PROJET) != 0) {
        alerte("Le dossier du projet est introuvable. Refabriquer l'application "
               "depuis le projet déplacé.");
        return 1;
    }

    pid_t enfant = fork();
    if (enfant < 0) {
        alerte("Lancement impossible : le système a refusé de créer le processus.");
        return 1;
    }

    if (enfant == 0) {
        execl(CHEMIN_UV, "uv", "run", "-m", "controle_vocal.reglages", (char *)NULL);
        _exit(127); /* uv est introuvable : le parent le traduira. */
    }

    int etat = 0;
    if (waitpid(enfant, &etat, 0) < 0) {
        return 1;
    }
    if (WIFEXITED(etat) && WEXITSTATUS(etat) == 127) {
        alerte("uv est introuvable. Le réinstaller, puis refabriquer l'application.");
        return 1;
    }
    return WIFEXITED(etat) ? WEXITSTATUS(etat) : 1;
}
